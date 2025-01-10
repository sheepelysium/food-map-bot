import re, json
from flask import Flask, request, abort
from urllib.parse import urlencode
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain.memory import ConversationBufferMemory
from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
    PromptTemplate
)
from typing import Optional, List

from configparser import ConfigParser
import requests
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
)

class LineBotApp:
    def __init__(self):
        self.app = Flask(__name__)
        
        config = ConfigParser()
        config.read("config.ini")
        self.channel_secret = config["LINEBOT"]["channel_secret"]
        self.channel_access_token = config["LINEBOT"]["channel_access_token"]
        self.gemini_api_key = config["GEMINI"]["API_KEY"]
        self.places_api_key = config["GOOGLE"]["PLACES_API_KEY"]
        self.ngrok_url = config["NGROK"]["url"]

        # 初始化 LINE 設定和 Gemini 模型
        self.configuration = Configuration(access_token=self.channel_access_token)
        self.handler = WebhookHandler(self.channel_secret)
        self.llm_gemini = ChatGoogleGenerativeAI(
            model="gemini-1.5-flash-latest",
            temperature=0.3,
            google_api_key=self.gemini_api_key
        )
        
        # 初始化 memory
        self.memory = ConversationBufferMemory(
            return_messages=True,  
            memory_key="chat_history",
            input_key="input",
            output_key="output"
        )
        
        self.setup_routes()

    def start(self, host='0.0.0.0', port=5000):
        self.app.run(host=host, port=port)
        
    def setup_routes(self):
        @self.app.route("/callback", methods=['POST'])
        def callback():
            # get X-Line-Signature header value
            signature = request.headers['X-Line-Signature']

            # get request body as text
            body = request.get_data(as_text=True)
            self.app.logger.info("Request body: " + body)

             # handle webhook body
            try:
                self.handler.handle(body, signature)
            except InvalidSignatureError:
                self.app.logger.error("Invalid signature. Please check your channel access token/channel secret.")
                abort(400)

            return 'OK'
        
        # 綁定處理訊息的邏輯
        @self.handler.add(MessageEvent, message=TextMessageContent)
        def handle_message(event):
            user_input = event.message.text
            self.app.logger.info(f"Received message from user: {user_input}")

            with ApiClient(self.configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                try:
                    reply_message = self.gemini_response(event.message.text)
                except Exception as e:
                    self.app.logger.error(f"Error in handle_message: {e}")
                    reply_message = "抱歉，目前系統發生問題，請稍後再試。"

                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_message)]
                    )
                )

    def gemini_response(self, user_input: str) -> str:
        """
        使用 Gemini 模型解析用戶的訊息，並根據輸出進行推薦或引導。
        """

        try:
            # Generate conversation content
            system_prompt = """
            你是一個了解台灣各地美食的在地專家，負責根據用戶的輸入進行餐廳推薦。

            請根據用戶的輸入，提取以下關鍵資訊並以標準 JSON 格式回傳：
            - location: 用戶提到的具體地點名稱。如果用戶沒有提到地點，則為 null。
            - food: 用戶提到的食物類型或餐點名稱。如果用戶沒有提到食物類型，則為 null。
            - recommendation_needed: 若同時缺少地點與食物類型，則回傳 false，否則回傳 true
            - guide_message : 當用戶輸入內容包含地點或食物類型時，回傳空值，當用戶輸入資訊不完整時，請友善的提供引導訊息。
            請直接回傳 JSON 結果，無需其他文字描述。

            範例：

            1. 用戶輸入：「推薦板橋的燒肉店」
            回應：
            ```json
            {{
                "location": "板橋",
                "food": "燒肉",
                "recommendation_needed": true,
                "guide_message": null
            }}
            """

            conversation = (
                ChatPromptTemplate.from_messages([
                    ("system", system_prompt),
                    MessagesPlaceholder(variable_name="chat_history"),
                    ("human", "{question}")
                ])
                | self.llm_gemini
                | StrOutputParser()
            )

            result = conversation.invoke({
                "chat_history": self.memory.load_memory_variables({}).get("chat_history", []),
                "question": user_input
            })
            # 去除可能的 Markdown 標記並解析 JSON
            cleaned_result = re.sub(r"```(json)?\n?", "", result).strip()
            parsed_response = json.loads(cleaned_result)

            location = parsed_response.get("location")
            food = parsed_response.get("food")
            recommendation_needed = parsed_response.get("recommendation_needed")
            guide_message = parsed_response.get("guide_message")
            # print(f"1. 地點 : {location}")
            # print(f"2. 食物 : {food}")
            # print(f"3. 是否需要推薦 : {recommendation_needed}")

            # 如果有 location 或 food，進行搜尋
            if recommendation_needed:
                places_results = self.textsearch_restaurants(location, food)
                if places_results:
                    # total_stores = self.print_store_list(places_results)
                    recommendation = self.generate_recommendation_message(places_results)
            else:
                recommendation = guide_message
            # 儲存對話內容
            self.memory.save_context(
                {"input": user_input},
                {"output": recommendation}
            )
            print(f"回應結果recommendation : {recommendation}")
            return recommendation

        except json.JSONDecodeError as e:
            self.app.logger.error(f"JSON 解析錯誤: {e}")
            return "抱歉，系統無法解析您的請求，請稍後再試。"
        except Exception as e:
            self.app.logger.error(f"呼叫gemini發生錯誤: {e}")
            return "抱歉，系統出現問題，請稍後再試。"


    def get_google_photo_url(self, photo_reference: str, max_width: int = 400) -> str:
        """
        根據照片引用生成 Google Places API 的照片 URL。
        
        :param photo_reference: Google Places API 返回的照片引用 ID。
        :param max_width: 照片最大寬度（預設為 400px）。
        :return: Google 的公開照片 URL。
        """
        base_url = "https://maps.googleapis.com/maps/api/place/photo"
        params = {
            "maxwidth": max_width,
            "photoreference": photo_reference,
            "key": self.places_api_key
        }
        return f"{base_url}?{urlencode(params)}"
        
    def textsearch_restaurants(self, location: str, food: Optional[str] = None, max_photos: int = 1, limit: int = 5) -> Optional[List[dict]]:
        """
        使用 Google Places API 搜尋附近的餐廳。
        """
        try:
            query = f"{location} {food}" if food else location
            base_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
            params = {
                "query": query,
                "type": "restaurant",
                "language": "zh-TW",
                "key": self.places_api_key
            }

            response = requests.get(base_url, params=params)
            response.raise_for_status()

            data = response.json()
            if data.get("status") != "OK":
                self.app.logger.error(f"Places API 錯誤狀態 : {data.get('status')}")
                return None

            results = data.get("results", [])[:limit]

            # 提取照片 URL
            for resto in results:
            #     photos = resto.get("photos", [])
            #     if photos:
            #         photo_references = [photo.get("photo_reference") for photo in photos[:max_photos]]
            #         resto["photo_urls"] = [self.get_google_photo_url(photo_ref) for photo_ref in photo_references]
            #     else:
            #         resto["photo_urls"] = ["無照片"]
                place_id = resto.get("place_id")
                if place_id:
                    resto["place_id"] = place_id
                    resto["filtered_reviews"] = self.get_high_rating_reviews(place_id)
            # print(f"7. 搜尋結果 : {results}")
            return results

        except Exception as e:
            self.app.logger.error(f"請求Places API發生錯誤 : {e}")
            return None
        
    def generate_recommendation_message(self, recommendations: List[dict], num_recommendations: int = 5, only_open: bool = False) -> str:
        """
        根據搜尋結果生成推薦訊息。
        """
        if not recommendations:
            return "抱歉，沒有找到符合條件的餐廳。"

        formatted_text = "為您推薦以下餐廳：\n"
        count = 0

        for resto in recommendations:
            if resto.get('business_status') != 'OPERATIONAL':
                continue
            if only_open and not resto.get('opening_hours', {}).get('open_now', False):
                continue

            count += 1
            if count > num_recommendations:
                break

            name = resto['name']
            rating = resto.get('rating', '無評分')
            address = resto.get('formatted_address', '無地址')
            reviews = resto.get('filtered_reviews', [])
            # 提取照片 URL（如果有）
            # photo_reference = resto.get('photos', [{}])[0].get('photo_reference')
            # photo_url = self.get_photo_url(photo_reference) if photo_reference else "無照片"

            formatted_text += f"{count}. {name}\n"
            formatted_text += f"   - 評分: {rating} 分\n"
            formatted_text += f"   - 地址: {address}\n"
            # formatted_text += f"   - 照片: {photo_url}\n"

            if reviews:
                recommend_text = self.summarize_reviews(name, reviews)
                formatted_text += f"   - 推薦: {recommend_text}\n\n"

        if count == 0:
            return "抱歉，沒有找到符合條件的餐廳。"

        return formatted_text
    
    def get_high_rating_reviews(self, place_id: str, min_rating: int = 4) -> List[str]:
        """
        使用 Places Details API 抓取4星以上的最新5筆評論。
        """
        url = "https://maps.googleapis.com/maps/api/place/details/json"
        params = {
            "place_id": place_id,
            "key": self.places_api_key,
            "language": "zh-TW"
        }
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            details = response.json().get("result", {})
            reviews = details.get('reviews', [])

            filtered_reviews = [
                review for review in reviews
                if review.get('rating', 0) >= min_rating and review.get('text')
            ]
            # print(f"6. 高分評論 : {filtered_reviews}")
            return [review.get('text') for review in filtered_reviews]

        except Exception as e:
            self.app.logger.error(f"請求Places Details API 時發生錯誤: {e}")
            return []
    
    def summarize_reviews(self, name: str, review_texts: List[str]) -> str:
        """
        根據評論生成摘要推薦文字
        """
        if not review_texts:
            return f"{name}是一家知名餐廳，提供多樣化的美食，值得一試！"

        prompt = PromptTemplate.from_template("""
        以下是一些顧客的高分評價：
        {review_texts}
        請從評論中找出 3 個核心賣點，並根據這些賣點生成一段約 50 字的推薦文字。
        
        推薦內容需要：
        1. 包含餐廳特色。
        2. 提及推薦餐點。
        3. 語氣要口語化且吸引人，不要過於浮誇。
        4. 餐廳間的評論內容請勿重複使用。
        """)
        
        # 將評論合併為單一字符串（用換行符分隔）
        combined_reviews = "\n".join(review_texts)

        prompt_input = {"review_texts": combined_reviews, "name": name}

        try:
            chain = (
                prompt 
                | self.llm_gemini 
                | StrOutputParser()
            )
            result = chain.invoke(prompt_input)

            return result.strip()
        
        except Exception as e:
            self.app.logger.error(f"使用 Gemini 生成推薦時發生錯誤 : {e}")
            return "抱歉，目前系統暫時無法提供完整的推薦，請稍後再試。"

    def print_store_list(self, results: List[dict]) -> int:
        """
        打印餐廳清單並計算總數
        """
        # 抓取所有店名
        store_names = [resto.get("name") for resto in results if resto.get("name")]
        
        # 統計店家數量
        store_count = len(store_names)
        print(f"共有 {store_count} 家店")
        for i, name in enumerate(store_names, start=1):
            print(f"第 {i} 家店：{name}")
        
        return store_count

bot_app = LineBotApp()
app = bot_app.app 
if __name__ == "__main__":
    # 啟動 Flask 應用
    bot_app.start()

# food-map-bot
專案簡介
FoodMap 是一個以 LINE Bot 為介面的美食推薦應用程式，使用 Google Places API 和 Gemini AI 提供基於使用者輸入的個人化餐廳推薦。此應用能分析使用者輸入的地點與食物類型，並回傳推薦的餐廳列表與相關資訊。

功能特色
1. 餐廳推薦：透過使用者提供的地點與食物類型，自動搜尋 Google Places API 並推薦符合條件的餐廳。
2. AI 驅動的訊息解析：使用 Gemini AI 解析使用者輸入，提取地點和食物類型，並生成推薦結果。
3. 評論分析與摘要：透過 Google Places API 抓取高分評論，並使用 Gemini AI 生成餐廳推薦摘要。
4. 自動回覆機制：透過 LINE Bot，自動回覆使用者的詢問與推薦結果。

使用技術
後端框架：Flask
LINE Bot SDK：line-bot-sdk v3
Google API：Google Places API（Text Search、Place Details）
AI 技術：Gemini AI（使用 LangChain 整合）
記憶功能：使用 LangChain 的 ConversationBufferMemory 儲存對話內容

LINE Bot 使用方式
加入 LINE Bot，輸入想要搜尋的餐廳地點與食物類型，例如：「推薦板橋的燒肉店」。
Bot 會回覆推薦的餐廳列表與簡要資訊，包括餐廳名稱、評分、地址和推薦原因。
若使用者輸入資訊不足，Bot 會引導使用者補充所需資訊。

未來計劃
增加更多推薦條件（例如價格範圍、營業時間）。
優化推薦演算法，提高推薦準確性。
增加圖片顯示功能，提升使用者體驗。
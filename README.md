# EngageBoost — AI Comment Generator

EngageBoost is a lightweight AI-powered tool designed to help users quickly generate meaningful, natural-sounding comments. Whether you're responding in online communities, writing product reviews, chatting in forums, or engaging with content across the web — EngageBoost makes thoughtful engagement fast and effortless.

---

## 🔧 How It Works

1. Type or paste text into the extension  
2. Choose a tone (professional, friendly, supportive, casual, etc.)  
3. Click **Generate**  
4. Copy your response with one click and paste it anywhere  

The extension communicates securely with the EngageBoost server to generate content using AI.

---

## 🚀 Components

| Component | Description |
|----------|-------------|
| **Chrome Extension** | Front-end interface used to generate comments |
| **This Repository** | Server used to process requests from the extension |
| **AI Backend** | Uses third-party AI services via API (depending on configuration) |

---

## 🔒 Privacy

No personal data is collected, stored, or sold.  
Only the text you choose to generate is processed by the server.

🔗 Privacy Policy:  
https://moodesburn1977.github.io/engageboost-server/privacy

---

## 🖥 Requirements

- Node.js (if hosting the server yourself)
- A valid API key for the AI provider used

---

## 📦 Installation (Server)

```bash
git clone https://github.com/Moodesburn1977/engageboost-server
cd engageboost-server
npm install
npm start


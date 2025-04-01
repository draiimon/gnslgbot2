# GINSILOG BOT: Render Deployment Guide (2025 Updated)

## Mga Kailangan
1. **GitHub Account** - Para sa code repository
2. **Render.com Account** - Para sa hosting
3. **Discord Developer Account** - Para sa bot token
4. **Firebase Project** - Para sa database storage

## Step 1: Maghanda ng mga Secret Keys
Kailangan mo ng mga sumusunod na secret keys:

1. **DISCORD_TOKEN**
   - Makukuha sa [Discord Developer Portal](https://discord.com/developers/applications)
   - Pumunta sa application mo, tapos sa "Bot" tab
   - Pindutan ang "Reset Token" para makita ang token

2. **GROQ_API_KEY**
   - Makukuha sa [GROQ Dashboard](https://console.groq.com)
   - Gumawa ng bagong API key kung wala ka pa

3. **FIREBASE_CREDENTIALS**
   - Pumunta sa [Firebase Console](https://console.firebase.google.com)
   - Piliin ang project mo
   - Project Settings > Service Accounts > Generate New Private Key
   - Buksan ang JSON file na na-download
   - **IMPORTANTE:** Kailangan i-paste ang BUONG CONTENT ng JSON file, KASAMA ang curly braces at lahat ng quotation marks

## Step 2: I-deploy ang Bot sa Render.com (Docker)

### A. I-setup ang Repository sa GitHub
1. I-upload ang code sa public o private GitHub repository
2. Siguraduhing kasama ang mga sumusunod na files:
   - `Dockerfile`
   - `render.yaml`
   - `render_requirements.txt`
   - `prestart.sh`

### B. Mag-deploy sa Render

1. Log in sa [Render Dashboard](https://dashboard.render.com)
2. Pindutin ang "New" button, tapos piliin ang "Blueprint"
3. Sa GitHub, i-connect ang repository mo kung hindi pa connected
4. Piliin ang repository na may Ginsilog Bot
5. Render will automatically detect the `render.yaml` file
6. Pindutin ang "Apply" button

### C. I-configure ang Environment Variables

1. Sa Render Dashboard, i-select ang web service na ginawa
2. Pumunta sa "Environment" tab
3. Idagdag ang mga sumusunod na environment variables:

   | Key | Value |
   |-----|-------|
   | DISCORD_TOKEN | Ang Discord bot token mo |
   | GROQ_API_KEY | Ang GROQ API key mo |
   | FIREBASE_CREDENTIALS | Ang buong content ng Firebase credentials JSON file |
   | RENDER | true |
   | DISABLE_PYAUDIO | false |

4. I-save ang mga changes

### D. Manual Deployment (Kung Kailangan)

1. Pumunta sa "Manual Deploy" tab
2. Piliin ang "Clear build cache & deploy"
3. Maghintay para ma-complete ang build at deployment

## Step 3: I-verify ang Deployment

1. Sa Render Dashboard, check ang "Logs" tab para makita kung gumagana nang tama
2. Dapat makita mo ang mga ganitong messages:
   ```
   ✅ Created Firebase credentials file
   ✅ Connected to Firebase Firestore in PRODUCTION MODE
   ✅ Firebase database initialized in PRODUCTION mode
   🔄 Running in Render environment - cogs will be initialized when bot is ready
   ✅ Full audio features enabled
   ✅ Logged in as GNSLG Bot (...)
   ```

3. Check sa Discord kung online ang bot mo at sumasagot sa mga commands

## Troubleshooting

### Bot Hindi Nag-o-online
1. **Check Render Logs**
   - Tingnan ang "Logs" tab sa Render Dashboard
   - Hanapin ang error messages

2. **Invalid Discord Token**
   - Siguraduhing nasa tamang format ang Discord token
   - I-regenerate ang token kung kinakailangan

3. **Firebase Credentials Error**
   - Kailangan buong JSON (kasama ang curly braces `{}`)
   - I-check kung may mga nawalang quotation marks o commas

4. **GROQ API Key Error**
   - I-verify kung valid pa ang API key
   - Gumawa ng bagong API key kung kinakailangan

5. **Rate Limit Issues**
   - Kung nakakita ka ng "rate limit" errors, hintayin lang ng ilang minuto at subukan ulit

## Mga Limitations sa Render Deployment

1. **Voice Recognition**
   - Hindi gumagana ang voice recognition/listening features dahil walang native PyAudio sa Render
   
2. **TTS/Voice Chat**
   - Gumagana ang Text-to-Speech features gamit ang Edge TTS

## Support at Updates

Kung may mga issues ka o kailangan mo ng tulong:
1. Check ang GitHub repository para sa updates
2. I-restart ang Render deployment kung nagka-problema

---

Updated: April 2025
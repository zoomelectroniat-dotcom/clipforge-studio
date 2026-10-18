# ClipForge Studio — FREE Test Deploy (Render)

Tumhare phone se test karne ke liye app ko internet par live karna hai. Ye **test** deploy hai — free, koi card nahi chahiye.

## Step 0 — Code GitHub par (pehle ye hoga)

Code ko `clipforge-studio` naam ke GitHub repo main push karna parega — ye main kar dunga (GitHub login connect hote hi). Tumhein kuch nahi karna.

## Step 1 — Render account banao (free)

1. **render.com** kholo
2. **"Sign up with GitHub"** dabao (apne `zoomelectroniat-dotcom` account se)
3. Koi credit card **nahi** mangta — free plan select rakho

## Step 2 — Web Service banao

1. Dashboard par **"New +"** → **"Web Service"**
2. **clipforge-studio** repo connect karo (GitHub authorize karna parega pehli dafa)
3. Settings:
   - **Runtime:** Docker
   - **Plan:** Free
   - **Health check path:** `/`
   - Baqi default rehne do (`render.yaml` blueprint bhi yehi karta hai — chaaho to "New → Blueprint" se repo select karo, sab auto-fill ho jayega)
4. **Create Web Service** dabao — pehla build ~5-10 minute lega (ffmpeg + models download hote hain)

## Step 3 — Secret values add karo (dashboard main, code main NAHI)

Service ke page par **"Environment"** tab → ye 5 variables add karo (values main tumhein alag se dunga — ye chat/file main nahi likhin):

| Variable | Value kahan se |
|---|---|
| `APP_URL` | Deploy ke baad milegi public URL (Step 4) |
| `GROQ_API_KEY` | Tumhari Groq key (AI transcription ke liye) |
| `GOOGLE_CLIENT_ID` | Google Cloud Console se (pehle bani hui) |
| `GOOGLE_CLIENT_SECRET` | Google Cloud Console se |
| `GOOGLE_REDIRECT_URI` | Deploy ke baad: `https://<tumhari-url>/auth/google/callback` |

**Save** dabate hi Render dobara deploy karega (~2-3 min).

## Step 4 — Google ko nayi URL batao (zaroori!)

Google login sirf registered URL par kaam karta hai:

1. Google Cloud Console → **APIs & Services → Credentials**
2. Tumhara OAuth client kholo
3. **Authorized redirect URIs** main ye add karo:
   `https://<tumhari-render-url>/auth/google/callback`
   (masalan: `https://clipforge-studio.onrender.com/auth/google/callback`)
4. Save

## Step 5 — Phone se test karo

1. Apni Render URL phone ke browser main kholo
2. **Demo login:** `demo@clipforge.studio` / `clipforge-demo-123` (60 free credits)
3. Video upload karo → clips banao → dekho!

## Free tier ki hadod (imandari se)

- **So jata hai:** 15 minute istemal na ho to service sleep ho jati hai — pehla khulna ~30-60 second lega, phir tez
- **Sab kuch reset:** Upload ki hui videos aur database restart/redeploy par **mit jati hain** — testing ke liye theek hai, asal istemal ke liye nahi
- **750 ghante/month** free — ek service ke liye kaafi hai
- **No GPU** — face detection CPU par chalti hai (thori slow, chalti hai)
- Build time ~5-10 min pehli dafa

## Jab test pass ho jaye → paid ka rasta

1. Render par **Starter plan** ($7/month): neend nahi aati, tez
2. **Persistent disk** add karo (uploads + DB bachenge) — ya Postgres ($7/month)
3. Apni domain lagao (masalan `clips.productiveaihub.com`) aur `GOOGLE_REDIRECT_URI`/`APP_URL` update karo

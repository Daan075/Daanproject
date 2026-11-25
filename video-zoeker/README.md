# Video Zoeker

Laat AI een YouTube-video of een **afgelopen** Twitch-stream "bekijken" en zoek er daarna in met gewone vragen:

- *"Geef alle momenten waarop hij moet lachen"*
- *"Wanneer begint missie 4?"*
- *"Wanneer gaat hij voor het eerst dood?"*
- *"Waar praat hij over zijn nieuwe pc?"*

Je krijgt een lijst met tijdstippen. Klik erop en de video springt naar dat moment.

## Hoe het werkt

1. **Downloaden**: de video wordt in lage resolutie (480p) gedownload met [yt-dlp](https://github.com/yt-dlp/yt-dlp).
2. **Spraak naar tekst**: lokaal op je eigen computer met Whisper (faster-whisper). Heeft een YouTube-video
   ondertitels, dan gebruikt de app die (dat is veel sneller).
3. **Geluiden herkennen**: een geluidsmodel (AudioSet) luistert de hele video af op lachen, giechelen,
   schreeuwen, applaus, explosies, muziek enz. Ook dit draait lokaal.
4. **Beelden bekijken**: elke ~10 seconden wordt een beeld uit de video naar Claude gestuurd. Claude beschrijft
   wat er te zien is en neemt tekst in beeld over (zoals missienamen, levels en scores). Beelden die niet
   veranderd zijn, worden overgeslagen.
5. **Zoeken**: je vraag gaat samen met de tijdlijn (wat er gezegd wordt, welke geluiden er zijn en wat er in beeld
   is) naar Claude. Claude zoekt de passende momenten op en legt uit waarom.

Bij elk zoekresultaat zie je een beeld van dat moment. Onder *"Direct uit de geluidsherkenning"* kun je ook
zonder AI-vraag (dus gratis) alle lachmomenten en andere herkende geluiden bekijken. Op het tabblad
*"Alles wat de AI zag"* zie je precies wat de AI van de video weet.

## Wat je nodig hebt

- Een **Windows-pc, Mac of Linux-computer**. Een NVIDIA-videokaart maakt het een stuk sneller, maar is niet nodig.
- **Python 3.10 tot en met 3.13** (3.12 aangeraden).
- **ffmpeg** (voor audio en beelden).
- **Deno** (yt-dlp heeft dit nodig om YouTube-video's te downloaden).
- Een **Anthropic API-sleutel** voor Claude. Die maak je aan op [console.anthropic.com](https://console.anthropic.com)
  onder *API Keys*. Je betaalt per gebruik (zie [Kosten](#kosten)).
- Ongeveer 3 GB vrije schijfruimte voor de programma's en modellen, en tijdelijk wat extra ruimte per video.

## Installeren

### Windows

Open *PowerShell* of *Opdrachtprompt* en installeer de benodigde programma's (eenmalig):

```
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install DenoLand.Deno
```

Sluit daarna het venster en open een nieuw venster (zodat de programma's gevonden worden).

Dubbelklik dan op **`start.bat`** in de map `video-zoeker`. De eerste keer installeert die alles
(dat duurt een paar minuten) en opent hij het bestand `.env` in Kladblok. Zet daar je sleutel achter
`ANTHROPIC_API_KEY=`, sla op en sluit Kladblok. De app opent vanzelf in je browser op
<http://localhost:8765>.

Daarna start je de app elke keer gewoon met een dubbelklik op `start.bat`.

### macOS

Met [Homebrew](https://brew.sh):

```
brew install python@3.12 ffmpeg deno
cd pad/naar/video-zoeker
./start.sh          # eerste keer: installeert alles en maakt .env aan
# zet je sleutel in .env (bijv. met: open -e .env)
./start.sh          # start de app
```

### Linux

```
sudo apt install python3 python3-venv ffmpeg     # of het equivalent voor jouw distributie
curl -fsSL https://deno.land/install.sh | sh
./start.sh
```

### Sneller met een NVIDIA-videokaart (optioneel)

Standaard draaien Whisper en het geluidsmodel op de processor. Heb je een NVIDIA-kaart, installeer dan de
CUDA-versie van PyTorch en zet in `.env` `WHISPER_MODEL=turbo`:

```
.venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cu128
```

(op macOS/Linux: `.venv/bin/python` in plaats van `.venv\Scripts\python`). Werkt de videokaart niet voor
Whisper, dan valt de app automatisch terug op de processor.

## Gebruik

1. Plak een link, bijvoorbeeld `https://www.youtube.com/watch?v=…` of `https://www.twitch.tv/videos/…`,
   en klik op **Analyseren**.
2. Je ziet de voortgang per stap. Je kunt al zoeken terwijl de analyse nog loopt; dan zoek je in wat er tot nu toe
   klaar is.
3. Typ je vraag bij **Slim zoeken** of klik op een van de voorbeeldvragen.
4. Klik op een tijdstip om naar dat moment te springen. Met de link onder elk resultaat open je de video op
   YouTube of Twitch op dat moment.

Je eerdere vragen worden bewaard per video. Alles staat in de map `data/` naast de app.

**Tips voor goede resultaten**

- Wees concreet: *"Wanneer begint de missie 'The Big Score'?"* werkt beter dan *"de grote missie"*.
- Vraag je naar *alle* momenten, zeg dat dan ("geef alle momenten …").
- Lachen wordt herkend aan het geluid, aan "haha" in de tekst en aan een lachend gezicht als er een facecam in
  beeld is. Het geluidsmodel hoort ook lachen uit de game of van anderen. Wil je alleen de streamer zelf, zeg dat
  dan in je vraag.

## Hoe lang duurt het?

Ruwe richtlijn voor een stream van **1 uur** op een gewone laptop zonder videokaart:

| Stap | Duur |
| --- | --- |
| Downloaden (480p) | 1 à 5 minuten, afhankelijk van je internet |
| Spraak naar tekst (Whisper `small`) | ±10 à 15 minuten (met YouTube-ondertitels: seconden) |
| Geluiden herkennen | ±5 à 10 minuten |
| Beelden bekijken (Claude) | ±3 à 5 minuten, tegelijk met de stappen hierboven |

Met een NVIDIA-videokaart gaan spraak en geluid vele malen sneller.

## Kosten

De app gebruikt standaard **Claude Opus 5.5** voor zowel de beelden als het zoeken. Ruwe schatting:

- **Beelden bekijken**: ongeveer $1 à $1,50 per uur video (eenmalig per video). Lange streams worden nooit
  meer dan 900 beelden (instelbaar met `MAX_FRAMES`), dus een stream van 4 uur kost ongeveer $3 à $4.
- **Een zoekvraag**: hangt af van de lengte van de video, want de hele tijdlijn gaat mee. Voor een video van
  1 uur ongeveer $0,15 à $0,30, voor een stream van 4 uur ongeveer $0,50 à $0,70. Vervolgvragen binnen 5
  minuten over dezelfde video zijn een stuk goedkoper (ongeveer $0,05 à $0,15), omdat de tijdlijn dan in de
  cache van de API staat.

Bij elke video toont de app een schatting van wat die tot nu toe gekost heeft. Wil je goedkoper, zet dan in
`.env` bijvoorbeeld `VISION_MODEL=claude-sonnet-5-5` (ongeveer half zo duur) of `claude-haiku-5-5` (veel
goedkoper, maar minder nauwkeurig). Spraak naar tekst en geluidsherkenning zijn gratis: die draaien op je eigen
computer.

## Instellingen

Alle instellingen staan (met uitleg) in [`.env.example`](.env.example). De belangrijkste:

| Instelling | Standaard | Betekenis |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | – | Je Claude API-sleutel (verplicht voor beelden en zoeken) |
| `VISION_MODEL` / `SEARCH_MODEL` | `claude-opus-5-5` | Claude-model voor beelden / zoeken |
| `WHISPER_MODEL` | `small` | `tiny`, `base`, `small`, `medium`, `large-v3`, `turbo` |
| `WHISPER_LANGUAGE` | automatisch | Bijv. `nl` of `en` om de taal vast te zetten |
| `FRAME_INTERVAL` | `0` (auto, ±10 s) | Om de hoeveel seconden een beeld bekijken |
| `MAX_FRAMES` | `900` | Maximum aantal beelden per video |
| `KEEP_MEDIA` | `false` | Video- en audiobestand na afloop bewaren |
| `COOKIES_FROM_BROWSER` | – | `chrome`, `firefox`, `edge` … voor abonnee-VOD's of als YouTube moeilijk doet |

## Problemen oplossen

- **"ffmpeg is niet gevonden"**: installeer ffmpeg (zie hierboven), open een nieuw venster en start opnieuw.
- **YouTube-download mislukt**: werk yt-dlp bij met `.venv\Scripts\python -m pip install -U "yt-dlp[default]"`
  en controleer of Deno geïnstalleerd is. YouTube verandert regelmatig iets, en yt-dlp loopt daar meestal snel
  achteraan.
- **"Sign in to confirm you're not a bot"** of een Twitch-VOD alleen voor abonnees: zet
  `COOKIES_FROM_BROWSER=chrome` (of de browser waarin je bent ingelogd) in `.env`.
- **"Deze stream is nog live"**: wacht tot de stream is afgelopen en de VOD beschikbaar is.
- **Er gaat iets mis halverwege**: klik op **Opnieuw proberen**. Stappen die al klaar zijn, worden niet
  overgedaan.
- **De Twitch-speler laadt niet**: gebruik de links onder de resultaten om op Twitch zelf naar het moment te gaan.

## Privacy

Downloaden, spraak naar tekst en geluidsherkenning gebeuren op je eigen computer. Naar Anthropic gaan alleen
de losse beelden (voor de beeldbeschrijving) en de tekstuele tijdlijn plus je vraag (bij het zoeken).
De app draait alleen op je eigen computer (`localhost`) en is niet vanaf internet bereikbaar.

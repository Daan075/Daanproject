# Temperatuur Uitgeest – dit jaar vs. vorig jaar

Een eenvoudige web-app die per dag de dag- (maximum) en nachttemperatuur (minimum) in Uitgeest
laat zien, vergeleken met dezelfde datum vorig jaar. Klik op een dag voor een grafiek met het
temperatuurverloop per uur van beide jaren.

## Online zetten (GitHub Pages)
1. Ga in GitHub naar **Settings → Pages**.
2. Kies bij *Source* **Deploy from a branch**, selecteer deze branch en map `/ (root)`, en klik **Save**.
3. Na een minuut staat de app op `https://<gebruikersnaam>.github.io/<repo>/`.

## Als app installeren
De app is een PWA (installeerbare web-app):
- **iPhone (Safari):** open de link → deelknop → **Zet op beginscherm**.
- **Android (Chrome):** open de link → knop **📲 Installeer app**, of menu ⋮ → **App installeren**.
- **Computer (Chrome/Edge):** installeer-icoon in de adresbalk.

De app opent dan zonder browserbalk en toont zonder internet de laatst geladen gegevens.

## Databronnen
- **Open-Meteo Historical Weather API** – ERA5-heranalyse van ECMWF/Copernicus (uurlijkse temperatuur op 2 m).
- **Open-Meteo Forecast API, model `knmi_seamless`** – KNMI HARMONIE, voor de laatste dagen
  (die nog niet in het archief staan) en de rest van vandaag. Deze worden gemarkeerd als *voorlopig*.

Locatie: Uitgeest, 52,529° N, 4,709° O.

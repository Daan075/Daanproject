# Temperatuur Uitgeest – dit jaar vs. vorig jaar

Een eenvoudige web-app die per dag de dag- (maximum) en nachttemperatuur (minimum) in Uitgeest
laat zien, vergeleken met dezelfde datum vorig jaar. Klik op een dag voor een grafiek met het
temperatuurverloop per uur van beide jaren.

## Gebruik
Open `index.html` in je browser, of host de map via GitHub Pages
(Settings → Pages → Deploy from branch). Er is geen installatie of API-sleutel nodig.

## Databronnen
- **Open-Meteo Historical Weather API** – ERA5-heranalyse van ECMWF/Copernicus (uurlijkse temperatuur op 2 m).
- **Open-Meteo Forecast API, model `knmi_seamless`** – KNMI HARMONIE, voor de laatste dagen
  (die nog niet in het archief staan) en de rest van vandaag. Deze worden gemarkeerd als *voorlopig*.

Locatie: Uitgeest, 52,529° N, 4,709° O.

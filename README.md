# Trading Guardrail Bot

Manueller Daytrading-Planer für iPad/Browser.

## Was der Bot macht
- Watchlist scannen
- einfache Trend-/Volatilitätsregeln prüfen
- Google-News-RSS nach Risikonews durchsuchen
- Stop, Ziel, Stückzahl, Einsatz, Risiko und Chance berechnen
- Tagesrisiko begrenzen
- Journal als CSV führen

## Was der Bot nicht macht
- keine Trade-Republic-Orderausführung
- keine garantierten Gewinne
- keine Anlageberatung
- keine sicheren Trades

## Lokal starten
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Auf dem iPad nutzen
Am einfachsten:
1. GitHub-Account erstellen.
2. Neues Repository anlegen.
3. app.py und requirements.txt hochladen.
4. Auf Streamlit Community Cloud gehen.
5. Mit GitHub verbinden.
6. Repository, Branch und app.py auswählen.
7. Deploy klicken.
8. Die erzeugte .streamlit.app-Adresse auf dem iPad in Safari öffnen.
9. In Safari: Teilen → Zum Home-Bildschirm hinzufügen.

## Nutzung mit Trade Republic
Der Bot gibt nur einen manuellen Plan aus. Du öffnest Trade Republic separat und entscheidest selbst, ob du eine Order eingibst.
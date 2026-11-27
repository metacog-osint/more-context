# Indicator charters

One charter per zone: key questions, an escalation ladder (Watch, Warning, Crisis) and the indicators
that move a zone up it. The analyst writes them (copy `TEMPLATE.md`); Claude converts each into catalog data that
the Phase 2 coder tags stories against, and shows the converted version before it is used.

First four, chosen because each has a known onset to backtest against:

| Zone | Onset for backtesting | Status |
| --- | --- | --- |
| 01_Ukraine_Conflict | 24 Feb 2022 full-scale invasion | waiting on the analyst |
| 10_Israel_Gaza_Lebanon | 7 Oct 2023 Hamas attack | waiting on the analyst |
| 11_Iran_Red_Sea | 13 Jun 2025 Israeli strikes on Iran | converted 18 Nov 2026 (`11_Iran_Red_Sea.json`), waiting on analyst review; no code reads it yet |
| 06_India_Pakistan | 7 May 2025 strikes (Operation Sindoor) | waiting on the analyst |

name: 15m Signal Scanner

on:
  schedule:
    # 每 15 分鐘自動執行一次 (UTC 0, 15, 30, 45 分)
    - cron: '*/15 * * * *'
  workflow_dispatch: # 支援手動隨時觸發測試

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v3

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'

      - name: Install Dependencies
        run: |
          pip install -r requirements.txt

      - name: Run Market Scanner
        env:
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
        run: |
          python signal_scanner_15m.py

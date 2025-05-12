# VasoAnalyzer Developer Notes (v2.5.1-dev)

This document is for internal use during development of the Python-based VasoAnalyzer toolkit.

---

## Project Setup (macOS / cross-platform)

```bash
git clone https://github.com/vr-oj/VasoAnalyzer.git
cd VasoAnalyzer_2.0
python3 -m venv vasoenv
source vasoenv/bin/activate
pip install -r docs/requirements.txt
```

Running the App
```bash
python src/main.py
```
You can also run and debug using VSCode:
	•	Open folder in VSCode
	•	Activate the vasoenv interpreter
	•	Run main.py with the play button or debugger

⸻

Code Style
	•	Uses Black formatter
	•	Line length: 88 characters
	•	Format on save: Enabled via .vscode/settings.json

⸻

Dev Branch Workflow
	•	Base branch: main
	•	Development branch: v2.5.1-dev
	•	Never commit .vscode/, vasoenv/, or __pycache__/
	•	Always open PRs into main when features are complete
	•	Use DEV_CHANGELOG.md to track meaningful commits

⸻

Additional Notes
	•	Uses PyQt5, matplotlib, numpy, pandas, tifffile
	•	App is bundled with PyInstaller for release builds
    ---
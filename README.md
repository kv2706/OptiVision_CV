# OptiVision CV — Image Quality Analyzer

A local full-stack image-quality analysis web app inspired by the supplied screenshots.

## Quick start (Windows)
1. Install Python 3.11 or newer from https://www.python.org/downloads/ and enable **Add Python to PATH**.
2. Extract this ZIP to a normal folder (for example, `Desktop\optivision_cv`).
3. Double-click `run_windows.bat`. The first run installs dependencies and can take a few minutes.
4. Open http://127.0.0.1:5000 in your browser.

## Main Admin demo account
- Email: `admin@optivision.local`
- Password: `Admin@12345`

Change the demo password before exposing this app to any network. This starter app is intended for local development and demonstration, not production deployment.

## Features
- Registration, sign-in, password hashing, sessions, user roles (`user` / `admin`), account enable/disable
- Admin dashboard with user and analysis counts, average score, recent analyses, and activity log
- Upload JPG, JPEG, PNG, WEBP images up to 12 MB
- Pixel-derived brightness, contrast, sharpness, blur, exposure, highlights, shadows, saturation, vibrance, approximate color temperature, color balance, noise and dynamic range
- Composite 0–100 quality score, practical suggestions, private per-user history, and profile name editing
- SQLite database created automatically as `optivision.db`; uploaded files are stored in `uploads/`

## Metric notes
These measurements are calculated from image pixels, but several are heuristic indicators. Color temperature is an approximate relative warm/cool index mapped to Kelvin-like units, not a calibrated camera white-balance measurement. Sharpness/blur and the overall quality score are useful comparative indicators, not an objective judgement of artistic quality. Different kinds of images have different ideal values.

## Reset local demo data
Stop the app, then delete `optivision.db` and the files inside `uploads/`. The database and demo admin account will be recreated the next time you start the app.

## Project structure
- `app.py` — Flask backend, authentication, SQLite, image analysis
- `templates/` — HTML templates
- `static/style.css` — responsive styling
- `uploads/` — analyzed images (created automatically)

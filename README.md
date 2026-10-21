# KPMG Telecom Solution — React Front End

This is a React + Vite front-end prototype for the Network Cost Assurance and Optimisation tool.

## Requirements
- Node.js LTS (includes npm)
- VS Code (optional but recommended)

## Install Node.js
1. Go to https://nodejs.org/
2. Download the LTS version for Windows.
3. Install it using the default options.
4. Close and reopen VS Code.
5. Open the VS Code terminal and run:
   ```bash
   node -v
   npm -v
   ```
   Both commands should print version numbers.

## Run this project
1. Extract the ZIP file.
2. In VS Code, choose **File → Open Folder** and open the extracted `kpmg_telecom_react_frontend` folder.
3. Open **Terminal → New Terminal**.
4. Run:
   ```bash
   npm install
   ```
5. When installation finishes, run:
   ```bash
   npm run dev
   ```
6. Open the local URL printed in the terminal, usually `http://localhost:5173`.

## Project structure
```text
kpmg_telecom_react_frontend/
├── index.html
├── package.json
├── README.md
└── src/
    ├── App.jsx
    ├── main.jsx
    └── styles.css
```

## Important: front end only
The interface currently supports:
- Uploading one base source file (Excel/CSV)
- Uploading multiple supporting files (Excel/CSV/PDF)
- Displaying selected files and their sizes
- Output format and processing options
- A visual processing pipeline and summary cards
- A downloadable JSON run-configuration summary

It does **not** yet parse the source files, derive T-numbers, map vendors/sites, randomize test fields, or generate the Master of Master database. Those capabilities need a backend processing engine. The “Validate upload setup” button is only a front-end demo and must not be treated as a successful data-processing run.

For company data, only use an approved local/company environment and follow your organization's security policy.

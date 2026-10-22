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
KPMG-Demo-Project/
├── index.html
├── package.json
├── README.md
├── .env.example        Front-end API URL
├── backend/            FastAPI backend (see backend/README.md)
└── src/
    ├── api.js          REST client for the backend
    ├── App.jsx
    ├── main.jsx
    └── styles.css
```

## Processing backend
The front end is connected to a local Python FastAPI backend in [`backend/`](backend/README.md). That README has
the exact Windows commands to install it, start it, run the tests and process the synthetic sample files.

The current phase covers:
- two upload sections:
  - **Source File**: required, with any filename;
  - **Supporting Data File(s)**: optional, zero or more reference files, recognised from their columns;
- the T-number rules are maintained in the backend (`backend/config/rule_config.json`) and are never uploaded;
- server-side validation of file types, worksheets, header rows and required columns;
- deriving `TNUMBER` and `SITE ID` for every record, with rule IDs, sources, statuses, conflicts and exceptions;
- downloading the master workbook, the mapping summary and the exception report.

Banking details, vendor enrichment and payment enrichment are out of scope for this phase.

The front end calls `http://localhost:8000` by default. Override it with `VITE_API_BASE_URL` in `.env.local` (see
`.env.example`).

For company data, only use an approved local/company environment and follow your organization's security policy.

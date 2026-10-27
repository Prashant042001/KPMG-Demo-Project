# Network Cost Assurance – T-number & Site ID backend

FastAPI service used by the React front end of **KPMG - Telecom Solution - Network Cost Assurance and Optimisation**.

**Current scope:** derive `TNUMBER` and `SITE ID` for every record of the uploaded source file, with full traceability,
and produce a master database in the final column layout (section 6). In that layout, vendor, banking, address and
lease fields are **synthetic demo values**: they are never read from any input.

Everything runs locally. No data is sent to external services. Uploaded files and generated outputs are held in
process memory only and are discarded after `NCA_JOB_TTL_MINUTES` (default 60 minutes).

---

## 1. Set up and run (Windows)

Prerequisites: Python 3.11 or later (tested with 3.13) and Node.js LTS.

### 1.1 Create and activate a virtual environment

PowerShell:

```powershell
cd "D:\KPMG Automation\KPMG-Demo-Project\backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks the activation script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use
Command Prompt instead:

```bat
cd /d "D:\KPMG Automation\KPMG-Demo-Project\backend"
.venv\Scripts\activate.bat
```

### 1.2 Install backend dependencies

```powershell
python -m pip install -r requirements.txt
```

### 1.3 Start the FastAPI server

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- Health check: <http://127.0.0.1:8000/api/health>
- Interactive API documentation: <http://127.0.0.1:8000/docs>

Optional settings go in `backend\.env` (copy `backend\.env.example`). The main ones are `NCA_ALLOWED_ORIGINS`,
`NCA_MAX_FILE_SIZE_MB` and `NCA_RULE_CONFIG_PATH`.

### 1.4 Start the existing React front end

Open a **second** terminal:

```powershell
cd "D:\KPMG Automation\KPMG-Demo-Project"
npm install
npm run dev
```

Open the URL printed by Vite, normally <http://localhost:5173>.

### 1.5 Configure the local API URL

The front end calls `http://localhost:8000` by default. To change it:

```powershell
cd "D:\KPMG Automation\KPMG-Demo-Project"
Copy-Item .env.example .env.local
notepad .env.local      # set VITE_API_BASE_URL=http://<host>:<port>
```

Restart `npm run dev` after changing it. If the front end runs on a different origin, add that origin to
`NCA_ALLOWED_ORIGINS` in `backend\.env` and restart the backend.

### 1.6 Run the automated tests

```powershell
cd "D:\KPMG Automation\KPMG-Demo-Project\backend"
.\.venv\Scripts\Activate.ps1
python -m pytest
```

The tests use synthetic data only (`samples/synthetic.py`).

### 1.7 Process a synthetic sample workbook

Generate the sample files:

```powershell
cd "D:\KPMG Automation\KPMG-Demo-Project\backend"
python -m samples.synthetic
```

This writes three files to `backend\samples\output\`:

| File | Upload section in the UI |
| --- | --- |
| `Synthetic_Source_File.xlsx` | **Source File** |
| `Synthetic_BTS_Site_Report_Schedule.xlsx` | **Supporting Data File(s)** (optional) |
| `Synthetic_Operational_Site_List_Summary.xlsx` | **Supporting Data File(s)** (optional) |

In the UI: upload the source file, plus any supporting files you want to use. Click **Validate files**, then click
**Run T-number & Site ID derivation**. Running with only the source file also works: the reference look-ups (R1, R28)
are skipped and reported against the affected records.

Without the UI (PowerShell, backend running):

```powershell
cd "D:\KPMG Automation\KPMG-Demo-Project\backend\samples\output"
curl.exe -F "source_file=@Synthetic_Source_File.xlsx" `
         -F "supporting_files=@Synthetic_BTS_Site_Report_Schedule.xlsx" `
         -F "supporting_files=@Synthetic_Operational_Site_List_Summary.xlsx" `
         -F "strict_matching=false" -F "output_format=xlsx" `
         http://127.0.0.1:8000/api/process
# -> {"job_id":"<job_id>","status":"queued"}
curl.exe http://127.0.0.1:8000/api/jobs/<job_id>
```

### 1.8 Maintaining the T-number rules

The approved rules live in the backend, in the version-controlled file `config/rule_config.json`, and users never
upload them. The file is checked when the server starts (a malformed file stops start-up) and reloaded for every
processing job.

- `rules`: one entry per approved rule, with its `id`, rule `kind`, source `column`, `status` and the approved
  `description`.
  - `status` is `approved` or `requires_confirmation`. A rule with `requires_confirmation` is reported but never
    executed.
  - The rule kinds are listed in `app/rules/catalog.py`.
- `patterns`: the regular expression for each pattern kind.
- `recognised_suffixes`: the approved suffixes for R7 and R21.
- `derivation`: priorities and the T-number composition switch.
- `version`: change it whenever the rules change. It is printed in every Processing Summary.

After editing the file, restart the backend and run `python -m pytest`.

### 1.9 Download the master workbook and reports

- **UI:** after the run completes, use **Master workbook**, **Mapping summary** and **Exception report**, or the
  sidebar links *Master database*, *Mapping review* and *Exceptions & review*.
- **API:**

```powershell
curl.exe -o master_database.xlsx  http://127.0.0.1:8000/api/jobs/<job_id>/download/master
curl.exe -o mapping_summary.xlsx  http://127.0.0.1:8000/api/jobs/<job_id>/download/mapping
curl.exe -o exception_report.xlsx http://127.0.0.1:8000/api/jobs/<job_id>/download/exceptions
```

The master workbook is always `.xlsx`. The mapping and exception reports follow the **Report format** option
(`.xlsx` or `.csv`).

---

## 2. API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Backend status |
| GET | `/api/config` | Upload contract, datasets and expected columns, approved rules, limits, options |
| POST | `/api/validate` | Validate files, worksheets, header rows and columns. Does not generate output. |
| POST | `/api/process` | Start a derivation job (returns `202` with a `job_id`) |
| GET | `/api/jobs/{job_id}` | Status, stage, progress, metrics, summary, 100-row preview |
| GET | `/api/jobs/{job_id}/records` | Search, filter and page through every derived row: `q` (text or row number), `status` (`all`, `tnumber_derived`, `tnumber_unresolved`, `site_id_unresolved`, `conflict`, `overridden`), `rule` (e.g. `R1`), `page`, `page_size` (max 500) |
| POST | `/api/gis` | GIS view without derivation: `supporting_files` = Operational Site List file(s), optional `source_file` = payment file. Returns a `job_id` for the two GIS endpoints below |
| GET | `/api/jobs/{job_id}/gis` | GIS view: sites from the Operational Site List (with coordinates, region, owner) and their linked payment counts and totals |
| GET | `/api/jobs/{job_id}/gis/sites/{site_id}` | One site's details and its payment rows from the master database (Vendor Name, VENDOR_SITE_CODE, Payment Date, Payment Amount) |
| GET | `/api/jobs/{job_id}/download/master` | Master workbook (6 sheets) |
| GET | `/api/jobs/{job_id}/download/mapping` | Mapping summary |
| GET | `/api/jobs/{job_id}/download/exceptions` | Exception report |

Multipart fields for `validate` and `process`:

- `source_file`: exactly one file, with any filename;
- `supporting_files`: optional; repeat the field once per file, or omit it entirely.

`process` also accepts `strict_matching` (`true`/`false`) and `output_format` (`xlsx`/`csv`).

---

## 3. Input files

There are two kinds of upload:

- **Source File** (required): the dataset to process. Every row is kept in the output, and the filename doesn't
  matter.
- **Supporting Data File(s)** (optional, zero or more): reference data. Each worksheet is identified from its
  columns.

| Dataset | Required columns (case- and punctuation-insensitive) | Needed for |
| --- | --- | --- |
| Source file | `VENDOR_SITE_CODE` **or** `Vendor Site`; optional `VENDOR_SITE_CODE_ALT` | everything |
| BTS Site Report Schedule (supporting) | `VENDOR_SITE_CODE`, `T number`; optional `VENDOR_SITE_CODE_ALT`, `Site ID` | R1, X-code validation, ALT values when the source has none |
| Operational Site List Summary (supporting) | `Account Number`, `Site ID`; optional for the GIS view: `Site Name`, `Region`, `Property Owner`, `Latitude` + `Longitude` (or one `Coordinates` column) | R28, X-code validation, GIS map |
| Latest Payment Data (supporting) | `Vendor Site` | recorded only (see section 8) |

- **No supporting dataset is mandatory.** If one is missing, the rules that need it are skipped. The exception report
  records this against each record that stayed unresolved (`MISSING_REFERENCE_DATA`).
- **Files are identified by their columns, not by filename.** A filename is used only to break a tie between two
  datasets whose columns a worksheet matches equally well.
- **Unusable supporting files don't stop the run.** A file that is unreadable, or matches no dataset, is reported
  as a warning.
- **Multiple files and worksheets:**
  - one workbook can hold several datasets in different worksheets;
  - several files of the same dataset are combined, and conflicts between them are flagged.
- **Header rows:** the worksheet and header row are detected automatically, and title rows above the header are
  allowed.

---

## 4. How the rules are applied

1. **Rule source:** the rules come from `config/rule_config.json` (section 1.8). Each rule names its kind and source
   column explicitly, so nothing depends on how a description is worded.
2. **Rules that are not executed** are listed for business confirmation. This applies to a rule:
   - with status `requires_confirmation`;
   - whose column is not configured;
   - that needs configuration the business has not approved yet (R7/R21 recognised suffixes).
3. **Duplicates:** a rule that repeats the logic of an earlier rule on the same column (R19 duplicates R18) is marked
   `DUPLICATE` and is evaluated once.
4. **Priority:** reference look-ups (R1 BTS, R28 Operational Site List) run first. Pattern rules follow in
   configuration order. `derivation.priority_overrides` can change this.
5. **Value cleaning:** before matching, each value is Unicode-normalised. Invisible characters (zero-width spaces,
   byte-order marks, soft hyphens) are removed, and the value is trimmed and upper-cased. The original value in the
   output is never changed.
6. **Candidates:** every rule is evaluated for every record, and each match becomes a *candidate*.
   - A failed or empty reference look-up never blocks a pattern rule.
7. **Resolution** (business instruction, 23 Oct 2026):
   - **R1 is authoritative.** When the BTS look-up (R1) yields a valid T-number, it is used even if other rules
     disagree. Those rules are marked `OVERRIDDEN BY R1` in the Mapping Summary and noted as Info-level
     `RESOLVED_BY_PRIORITY` exceptions, and the Conflict Indicator stays `N`.
   - **Without R1, priority decides.** If R1 yields nothing (no match, blank or `NA`, or several T-numbers), the
     highest-priority other rule wins. The `VENDOR_SITE_CODE` rules come first (R2–R14, R30, R31), then the ALT rules
     (R15–R27). A T-number composed from an Operational Site List Site ID (R28) is used only when no pattern finds
     one. Disagreeing lower-priority rules are noted as `RESOLVED_BY_PRIORITY` (Info). To flag them as conflicts
     instead, set `derivation.flag_resolved_conflicts` to `true`.
   - **Consistent pairs.** `SITE ID` comes from the same rule as the selected `TNUMBER`, so the output never mixes
     values from two rules.
   - **Ambiguity is still flagged.** If one rule finds several values (for example, two T-numbers in one field, or
     several T-numbers for one code in the BTS data), the record is flagged, unless R1 overrides it.
   - **Strict matching** (sidebar toggle): disagreements that R1 doesn't settle are withheld instead of resolved by
     priority.
8. **Cross-record conflicts:** the same Vendor Site Code resolving to different values across records is flagged as a
   conflict.
9. **Unresolved values:**
   - When no T-number can be derived, `TNUMBER` is `NA` in the Master Database (`cannot be derived` in the Derivation Trace).
   - When no Site ID can be derived, `SITE ID` is left blank and flagged.
   - Site IDs never carry prefixes or suffixes (`/E`, `/ELEC`, `MTN`, `T`).
   - An all-zero number (`T0000`, `X000`) is treated as a placeholder and never becomes a T-number or Site ID.

| Rule kind | Example | TNUMBER | SITE ID |
| --- | --- | --- | --- |
| R1 BTS look-up | `VS-100` → BTS `T4321` | `T4321` | BTS `Site ID` if present, otherwise `4321` |
| R2/R15/R29 | `T6542` | `T6542` | `6542` |
| R3/R16 | `3133MTN` | `T3133` | `3133` |
| R4/R17 | `X8754` | – | `X8754` only if found in reference Site IDs, otherwise flagged `UNVERIFIED` |
| R5/R18 | `T8646/ELEC` | `T8646` | `8646` |
| R6/R20 | `T7386/E` (not `/ELEC`) | `T7386` | `7386` |
| R8/R22 | `ABC-T8102-RENT` | `T8102` | `8102`; several T-numbers in one field are flagged |
| R10/R23, R11/R24 | `4455MTN/S`, `4456MTN/E` | composed `T4455` | `4455` |
| R12/R25 | `MTN77881` | composed `T77881` | `77881` |
| R13/R26 | `5566-LEASE` | composed `T5566` | `5566` |
| R14/R27 | `0123` | `cannot be derived` (T123 is not a valid T-number) | `123` |
| R30 (business instruction 23 Oct 2026) | `T000-1234`, `T000/1234` (`T` + zeros + `-` or `/` + 4–5 digits, whole value) | `T1234` | `1234` |
| R31 (business instruction 23 Oct 2026) | `T590MTN` (`T` + 3–5 digits + `MTN`, whole value) | `T590` | `590` |
| R28 Operational Site List | Account Number = Vendor Site Code | composed from Site ID | Site ID |
| R9 | modifier | allows 4–5 digit T-numbers | |

---

## 5. GIS analysis

The **GIS Analysis** button (or *GIS analysis* in the sidebar) opens a map of the sites in the Operational Site List
Summary.

The page has two modes, chosen at the top:

**With T-number derivation** (linked to the master database):
- The map belongs to a **completed processing run**. Each run links every site to the master-database rows whose
  derived `SITE ID` equals the site's `Site ID`. Leading zeros are ignored, so `0123` matches `123`.
- Before any run has completed, this mode asks you to run the T-number & Site ID derivation first.
- The latest run is remembered across page refreshes for as long as the backend keeps it (`NCA_JOB_TTL_MINUTES`,
  default 60). After that, run again.

**Without T-number derivation** (`POST /api/gis`):
- Upload the Operational Site List Summary (required) and, optionally, a payment file. No rules are run.
- A payment row is linked to a site by its own `Site ID` column when it has a valid one; otherwise when its
  `VENDOR_SITE_CODE` / `Vendor Site` equals exactly one site's `Account Number`. Rows that match an Account Number
  listed under several Site IDs are not linked. The page reports how many rows were linked each way.
- The T-number shown comes from the payment file's own `T number` column, if it has one.
- Without a payment file, the map shows site details only.

**Using the map:**
- Click a site, on the map or in the list, to see:
  - its `Site ID`, `Site Name`, `Property Owner`, `Region`, T-number and coordinates, from the Operational Site List;
  - its payment rows from the master database: `Vendor Name`, `VENDOR_SITE_CODE`, `Payment Date` and
    `Payment Amount`.
- The column headers shown are the ones found in your source file.

**What the map needs:**
- **Coordinates:** latitude and longitude columns such as `Latitude` / `Longitude` or `GPS_DEC_LATITUDE` /
  `GPS_DEC_LONGITUDE` (all accepted names are in `columns.LATITUDE` / `columns.LONGITUDE` of
  `config/rule_config.json`), or one `Coordinates` column (`-26.2041, 28.0473`).
  - Decimal degrees (`-26.2041`, a decimal comma is also accepted) and degrees-minutes-seconds (`26°12'15"S`,
    `S 26 12 15`) are read.
  - If a sheet has several latitude columns (e.g. `GPS_LATITUDE` and `GPS_DEC_LATITUDE`), the decimal one is used.
  - Sites without coordinates are listed but not plotted, and the page names the coordinate columns it found.
- **Paid sites not in the site list** can't be plotted. They are listed as links, so their payments can still be
  opened.
- **Map background tiles** come from OpenStreetMap by default. Only the visible map area is requested; no site or
  payment data is sent. If public tiles aren't allowed, set `VITE_MAP_TILE_URL` in `.env.local` to a
  company-approved tile server. If tiles can't load, the sites are still plotted on a blank background.

---

## 6. Outputs

**Master workbook** (`master_database_<job>.xlsx`), headers frozen and filterable:

1. **Master Database**: one row per source row, in the final 64-column layout defined in
   `app/output/master_layout.py` (`MASTER_COLUMNS`). Each column has one of these sources:
   - **Derived:** `TNUMBER` and `SITE ID`. `TNUMBER` is `NA` where no T-number can be derived.
   - **Base payment data** (`Vendor Name`, `Vendor Site Code`, `Invoice Number` … `Historical years payments released
     in current year`): copied unchanged from the source column with the same header (case- and
     punctuation-insensitive; `INVOICE_NUM` and `Vendor Site` are also accepted). It is left blank when the source has
     no such column, and the Processing Summary lists those columns.
   - **Operational data** (`Site Status`, `Site Name`, `Site Owner`, `Latitude`, `Longitude`): taken from the
     Operational Site List Summary row whose `Site ID` equals the derived `SITE ID`, otherwise `NA`.
   - **Randomized / Unused:** synthetic demo values (South African banks with their universal branch codes,
     addresses, VAT and company registration numbers, lease dates and so on). They are generated deterministically:
     vendor-level fields from the vendor name, lease-level fields from the vendor site code. A vendor therefore keeps
     the same details on every row and in every run.
   - **Rules:** `Payment Type` is `Rental + Fixed` when the invoice number starts with `PN`, otherwise
     `Variable Electricity`. `Bank Account Name` is the `Vendor Name`.
2. **Derivation Trace**: `Source Row`, then the derived fields and the traceability fields `Original Vendor Site Code`,
   `Original VENDOR_SITE_CODE_ALT`, `Candidate T-number(s)`, `T-number Rule ID`, `Site ID Rule ID`,
   `T-number Derivation Source`, `Site ID Derivation Source`, `T-number Derivation Status`,
   `Site ID Derivation Status`, `Conflict Indicator` and `Exception Reason`. The derivation sources read
   `<dataset>: <file> | <field>`. Here `TNUMBER` keeps the internal text `cannot be derived`.
3. **Mapping Summary**: one row per rule match per record, showing:
   - source dataset, file, field, original value and matching key;
   - the derived values and rule ID;
   - the status (`SELECTED`, `SUPPORTING`, `CONFLICTING`, `AMBIGUOUS`, `INVALID`, `UNVERIFIED`).
4. **Exceptions**, by category:

   | Category | Meaning |
   | --- | --- |
   | `UNRESOLVED_TNUMBER`, `UNRESOLVED_SITE_ID` | No value could be established |
   | `MISSING_SOURCE_VALUE` | The record has no Vendor Site Code to derive from |
   | `MISSING_REFERENCE_DATA` | A reference dataset was not supplied, so its rules could not check this record (also listed once per rule) |
   | `INVALID_CANDIDATE` | A value was found but fails the approved T-number or Site ID format |
   | `MULTIPLE_CANDIDATE_IDENTIFIERS` | Several T-numbers appear in one field |
   | `AMBIGUOUS_REFERENCE_MAPPING` | The reference data maps the key to several different values |
   | `CONFLICTING_MAPPING` | Rules, or records with the same code, disagree |
   | `UNVERIFIED_IDENTIFIER` | An X-code was not found in the reference data |
   | `RULE_REQUIRES_CONFIRMATION` | A rule was not executed, pending a business decision |
   | `MISSING_COLUMN`, `OPTIONAL_SOURCE_NOT_USED`, `DATA_QUALITY` | File-level information |

5. **Processing Summary**:
   - row and file counts;
   - T-numbers derived, unresolved and conflicting, with the measured match rate and **derivations per rule ID**;
   - status counts, exception counts and rule execution counts;
   - reference statistics;
   - the rule configuration version, and the assumptions that need confirmation.
6. **Rule Audit**: for each rule, its ID, description, priority, records evaluated, matches, selections, exceptions
   and confirmation status.

**Derivation statuses:**

- `TNUMBER`: `MAPPED` (from reference data), `DERIVED` (from a pattern), `COMPOSED` ('T' + Site ID),
  `NOT_DERIVED` or `CONFLICT_WITHHELD`.
- `SITE ID`: `MAPPED`, `DERIVED`, `UNVERIFIED`, `UNRESOLVED` or `CONFLICT_WITHHELD`.

---

## 7. Security controls

- **Uploads:**
  - only `.xlsx`, `.xls` and `.csv` are accepted;
  - file contents must match their extension (magic bytes);
  - each file is limited to `NCA_MAX_FILE_SIZE_MB` and checked while streaming;
  - zip-bomb checks are applied to `.xlsx` files;
  - XML is parsed through `defusedxml`.
- **Formulas:** they are never evaluated. Workbooks are read with cached values only.
- **Formula injection in outputs:**
  - `.xlsx`: every text cell is written as a literal string, so `=…` is stored as text and never as a formula;
  - `.csv`: text starting with `= + - @` (other than plain numbers) is prefixed with `'`.
- **Filenames:** uploaded filenames are sanitised. Download filenames are generated by the server.
- **Job IDs:** these are random 128-bit values, validated by pattern.
- **Errors and logs:**
  - API errors never contain file-system paths or stack traces;
  - logs contain counts and job-ID prefixes only, never cell values.
- **No persistence:**
  - data stays in memory only, with a time-to-live and a cap on the number of jobs;
  - spooled upload temp files are closed immediately.
- **CORS:** restricted to `NCA_ALLOWED_ORIGINS`.

---

## 8. Items requiring business confirmation

These items appear in every run's *Processing Summary* and *Rule Audit*:

1. **R7 / R21 recognised suffixes:**
   - The approved rules name only `/ELEC` (R5) and `/E` (R6) as suffixes, and both already have their own rules.
   - R7 and R21 need the explicit list of *other* approved suffixes or delimiters (for example `/S` or `-RENT`).
   - Until that list is provided, they are not executed, so text is never stripped arbitrarily.
   - Codes with a T-number followed by other text are still derived by the embedded rules R8 and R22.
   - Once approved, add the suffixes as regex fragments to `recognised_suffixes.values`. R7 and R21 then run with no
     other change.
2. **T-number composition:**
   - For Site-ID-only rules (R10–R13, R23–R26, R28), `TNUMBER` is composed as `T` + Site ID, following the
     convention in R3.
   - It is only composed when the result passes the T-number format.
   - To switch this off, set `derivation.compose_tnumber_from_site_id` to `false`.
3. **R9 scope:** 4–5 digit T-numbers are applied to every T-number rule.
4. **R13 vs R14 overlap:** values that start with `0` are handled by R14 (leading zero), not by R13.
5. **R4 / R17 X-codes:**
   - The X-code is read from the start of the value; trailing text is allowed, so `X100323 Zuikerbolsche TX` gives
     `X100323`.
   - **Business instruction (22 Oct 2026):** an X-code is mapped to both `TNUMBER` and `SITE ID` (the complete
     code, e.g. `X100323`).
   - `VENDOR_SITE_CODE` is checked first (R4), then `VENDOR_SITE_CODE_ALT` (R17). A T-number found in the code still
     takes precedence.
   - An X-code that is not in the reference data is still mapped, but it gets an Info-level `UNVERIFIED_IDENTIFIER`
     note for audit.
   - Settings in `x_codes`:
     - `accept_without_reference: false` restores reference-only validation, where unverified codes are flagged
       instead of mapped;
     - `map_to_tnumber: false` limits X-codes to `SITE ID`.
6. **Placeholder values:** reference cells containing `NA`, `N/A`, `#N/A`, `NULL`, `NONE`, `-` or `--` are treated
   as blank (`missing_value_markers`).
7. **Paired values:** when the code and the ALT disagree and no reference dataset gives a Site ID, `SITE ID` is
   taken from the same rule as the selected `TNUMBER`, and the record is flagged as a conflict.
8. **R29 / Latest Payment Data:** R29 is applied when the source file has a `Vendor Site` column. Latest Payment Data
   uploaded as a supporting file is recorded as *not used*, because no join key to the source records has been
   confirmed.
9. **R1 Site ID:** R1's description says the T-number is retrieved "as the Site ID". The engine uses the BTS
   `Site ID` column when present, and otherwise the numeric part of the T-number.

---

## 9. Project layout

```text
backend/
├── app/
│   ├── main.py              FastAPI app, CORS, error handlers
│   ├── config.py            Settings (NCA_* environment variables) and rule-config loader
│   ├── api/routes.py        REST endpoints, streaming upload limits
│   ├── core/                Errors, text normalisation
│   ├── ingest/              Safe file reading, header and worksheet detection, column matching, input validation
│   ├── rules/               Rule kinds and the loader for the approved rule configuration
│   ├── derivation/          Identifier formats, reference indexes, derivation engine
│   ├── output/writer.py     Master workbook, mapping and exception reports
│   └── services/            Pipeline orchestration, in-memory job store
├── config/rule_config.json  Column aliases, file roles, identifier formats, patterns, priorities
├── samples/synthetic.py     Synthetic sample data generator
├── tests/                   pytest suite
├── requirements.txt
└── .env.example
```

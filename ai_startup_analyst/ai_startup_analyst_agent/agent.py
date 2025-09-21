from google.adk.agents import SequentialAgent
from google.adk.agents import Agent
from google.adk.agents import LlmAgent
from google.cloud import bigquery
import json
import uuid
import datetime
from typing import List, Dict, Any

# -------------------------
# Tool: BigQuery loader
# -------------------------
def load_raw_json_data_to_bigquery(raw_json_data: str) -> dict:
    """
    Loads a JSON ARRAY (list of objects) into BigQuery using load_table_from_json.
    Expects `raw_json_data` to be a JSON-serialized string representing a list of dicts.
    Returns {"status":"success", "inserted_rows": N} on success, otherwise an error dict.
    """
    print("=== load_raw_json_data_to_bigquery called ===")
    # Print only prefix to avoid excessively long logs
    try:
        print((raw_json_data[:1000] + '...(truncated)') if raw_json_data and len(raw_json_data) > 1000 else raw_json_data)
    except Exception:
        print("raw_json_data (unprintable)")

    if raw_json_data is None or raw_json_data == "":
        print("ERROR: raw_json_data is empty or None")
        return {"status": "error", "message": "raw_json_data empty"}

    try:
        rows_to_insert = json.loads(raw_json_data, strict=False)
    except Exception as e:
        print("ERROR: invalid JSON passed to tool:", repr(e))
        return {"status": "error", "message": f"invalid JSON: {e}"}
    
    if not isinstance(rows_to_insert, list):
        print("ERROR: expected a JSON array (list) of rows")
        return {"status": "error", "message": "expected JSON array (list)"}

    # Basic schema validation for each row (ensures required fields exist)
    required_fields = {"source_id", "company_id", "company_name", "source_type", "received_at", "file_name", "raw_content_text"}
    bad_rows = []
    for i, r in enumerate(rows_to_insert):
        if not isinstance(r, dict):
            bad_rows.append({"index": i, "error": "row not an object"})
            continue
        missing = required_fields - set(r.keys())
        if missing:
            bad_rows.append({"index": i, "missing_fields": list(missing)})

    if bad_rows:
        print("ERROR: schema validation failed for some rows:", bad_rows)
        return {"status": "error", "message": "schema validation failed", "details": bad_rows}

    client = bigquery.Client()
    table_id = "micro-dynamo-472018-d2.ai_analyst.raw_data"
    print(f"Starting load job for {len(rows_to_insert)} rows into {table_id} at {datetime.datetime.utcnow().isoformat()}Z")

    try:
        # load_table_from_json performs a load job (file-like ingest)
        load_job = client.load_table_from_json(rows_to_insert, table_id)  # returns a LoadJob
        load_job_result = load_job.result()  # wait for completion
    except Exception as e:
        print("ERROR: exception while starting/waiting for load job:", repr(e))
        return {"status": "error", "message": f"exception during load job: {e}"}

    # Check job errors if any
    job_errors = getattr(load_job, "errors", None)
    if job_errors:
        print("Load job completed with errors:", job_errors)
        return {"status": "error", "message": "load job returned errors", "details": job_errors}

    inserted = getattr(load_job, "output_rows", None)
    if inserted is None:
       
        inserted = len(rows_to_insert)

    print(f"Load job succeeded. Inserted rows (approx): {inserted}")
    return {"status": "success", "inserted_rows": inserted}


# -------------------------
# Sub-agent: extractor + loader
# -------------------------
extract_load_raw_data_agent = Agent(
    name="extract_load_raw_data_agent",
    model="gemini-2.0-flash",
    description=(
        "A data extraction and ingestion AI agent. It receives files and a company name from the root agent, "
        "extracts raw text from the files, formats the data into a JSON array with required fields, loads the JSON into BigQuery "
        "by calling the load_raw_json_data_to_bigquery tool, and finally returns a simplified JSON (company_id, company_name, raw_content_text) to the root agent."
    ),
    instruction=(
"""
You are a data extraction and ingestion AI agent. YOU DO NOT INTERACT WITH USERS DIRECTLY.
You will ONLY receive inputs from the root agent and return outputs to the root agent.

--- REQUIRED FLOW (follow exactly) ---
1) Receive inputs (company_name and files list). For each file extract the complete raw text.
2) For each file produce an json object with the exact fields:
Json Format: "{
  "source_id": "string", // Unique id
  "company_id": "string",   // company id is company name + current date (ddMMYYYY)
  "company_name": "string", // company name 
  "source_type": "string", // source type like pitch decks, founder listing document, founder calls, call transcripts, emails, news reports etc
  "received_at": "timestamp", // current timestamp in IST format
  "file_name": "string",  // file name of the file 
  "raw_content_text": "string" // complete raw text data extracted from file 

}"
3) Create a single JSON ARRAY string of these objects (this string will be passed to the tool) 
Example JSON array : [{"source_id": "76bf4ecb-d2ca-4451-88fe-e5a46cd02c4a", "company_id": "comp_12345", "company_name": "Tech Innovators Inc.", "source_type": "pitch deck", "received_at": "2025-09-19T06:02:50.290969", "file_name": "pitch_deck_v1.pdf", "raw_content_text": "This is the raw text content of the pitch deck..."}, {"source_id": "8896f608-1a3f-4e07-99de-6b444cb2acf4", "company_id": "comp_67890", "company_name": "Future Solutions", "source_type": "email", "received_at": "2025-09-19T06:02:50.290986", "file_name": "email_from_founder.eml", "raw_content_text": "Hello team, please find attached the new report..."}]

--- IMPORTANT: JSON SERIALIZATION & ESCAPING ---
When you build the JSON ARRAY in step 3 you MUST produce a single JSON-serialized STRING that is safe to parse back into JSON. Concretely:
- Do NOT include unescaped raw newline, tab, carriage return, or other control characters inside the `raw_content_text` value.
- Ensure these are encoded/escaped (for example as "\\n", "\\t", "\\r") so the resulting JSON string is valid.
- The final value you pass to the tool must be the serialization of the array (exactly as produced by `json.dumps(array, ensure_ascii=False)`): a single string containing the whole JSON array.
- When calling the tool `load_raw_json_data_to_bigquery`, pass that serialized string as the `raw_json_data` argument. Example:
  {
    "tool": "load_raw_json_data_to_bigquery",
    "arguments": { "raw_json_data": "<the json.dumps(...) serialized string here>" }
  }
This guarantees the tool can `json.loads(raw_json_data)` without errors.

4) YOU MUST CALL the tool named `load_raw_json_data_to_bigquery` and pass the JSON string as the argument named `raw_json_data`.
   Wait for the tool's response. Do not return or output the JSON array before the tool returns.
   Only if the tool returns {"status":"success"} should you then RETURN the final simplified JSON array of objects with exactly these keys:
     [{ "company_id": "...", "company_name": "...", "raw_content_text": "..." }, ... ]
   Return **only** that JSON array (no explanations, no extra fields, no wrapper).
   in case error in tool then retry once (total 2) then error return error output
5) If the tool returns an error, include entries for each affected file with status="error" and error_message, but continue to attempt other files.
6) If a file cannot be processed at all, include a JSON object for it with status="error" and an error_message field.

--- IMPORTANT CONSTRAINTS ---
- Do not include any extra top-level fields in the JSON passed to BigQuery.
- Do not send any text or commentary to the user or root agent during processing. Only return the final simplified JSON array after a successful BigQuery load.
- Use this exact tool name: load_raw_json_data_to_bigquery (the runtime maps this to the Python function).
- Serialize the JSON array to a STRING when calling the tool (json.dumps(..., ensure_ascii=False)).
- Timestamps must be IST (Asia/Kolkata) timezone in ISO format.
- company_id must be company name (normalized: lowercase, spaces replaced with underscores) + "_" + date in ddMMyyyy (e.g., "tech_innovators_19092025").

--- EXAMPLE (human-readable) ---
1) Build the full array:
   [
     { "source_id": "uuid", "company_id": "comp_19092025", "company_name": "...", "source_type": "pitch deck", "received_at": "2025-09-19T12:00:00+05:30", "file_name": "x.pdf", "raw_content_text": "..." },
     ...
   ]
2) CALL TOOL:
   {
     "tool": "load_raw_json_data_to_bigquery",
     "arguments": { "raw_json_data": "<the json array serialized to a string>" }
   }
3) WAIT for tool response. If success -> retuen simplified JSON as described above (ONLY JSON array).
"""
    ),
    tools=[load_raw_json_data_to_bigquery],
    output_key="raw_file_text_data"
)


def load_structured_data_to_bigquery(structured_json: str) -> dict:
    """
    Loads ONE structured JSON object into BigQuery using load_table_from_json.
    Expects `structured_json` to be a JSON-serialized string (i.e., json.dumps(obj)).
    Returns {"status":"success", "inserted_rows":1} on success; otherwise returns an error dict.
    """
    print("=== load_structured_data_to_bigquery called ===")
    try:
        print((structured_json[:1000] + '...(truncated)') if structured_json and len(structured_json) > 1000 else structured_json)
    except Exception:
        print("structured_json (unprintable)")

    if structured_json is None or structured_json == "":
        print("ERROR: structured_json is empty or None")
        return {"status": "error", "message": "structured_json empty"}

    try:
        obj = json.loads(structured_json)
    except Exception as e:
        print("ERROR: invalid JSON passed to tool:", repr(e))
        return {"status": "error", "message": f"invalid JSON: {e}"}

    # Optional minimal validation: require company_id and company_name to be present
    required_core = {"company_id", "company_name"}
    missing_core = required_core - set(obj.keys())
    if missing_core:
        print("ERROR: missing required core fields for structured data:", missing_core)
        return {"status": "error", "message": "missing required core fields", "details": list(missing_core)}

    client = bigquery.Client()
    table_id = "micro-dynamo-472018-d2.ai_analyst.companies"
    print(f"Starting structured-data load for company_id={obj.get('company_id')} into {table_id} at {datetime.datetime.utcnow().isoformat()}Z")

    try:
        # pass a list containing single object
        load_job = client.load_table_from_json([obj], table_id)
        load_job_result = load_job.result()
    except Exception as e:
        print("ERROR: exception while starting/waiting for structured load job:", repr(e))
        return {"status": "error", "message": f"exception during load job: {e}"}

    job_errors = getattr(load_job, "errors", None)
    if job_errors:
        print("Structured load job completed with errors:", job_errors)
        return {"status": "error", "message": "load job returned errors", "details": job_errors}

    inserted = getattr(load_job, "output_rows", None)
    if inserted is None:
        inserted = 1

    print("Structured load job succeeded.")
    return {"status": "success", "inserted_rows": inserted}


# -------------------------
# Structured-data extractor (LLM agent) — updated to call the BQ tool
# -------------------------
extract_load_structured_data = LlmAgent(
    name="extract_load_structured_data",
    # https://ai.google.dev/gemini-api/docs/models
    model="gemini-2.0-flash",
    description="analyse raw data of company and extract structured data as JSON",
    instruction=(
        """
--- PRECONDITION (MUST) ---
You MUST only run if you receive input with the key "raw_file_text_data".
That value must be either:
 - a JSON STRING that is a serialized array of objects, OR
 - a JSON array (list) of objects.
Each object must contain "company_id", "company_name", and "raw_content_text".
If this precondition is not met, immediately return:
{ "error": "MISSING_RAW_FILE_TEXT_DATA" }
and do not attempt to parse, infer, or call other agents/tools.

--- MAIN TASK ---
You are a startup analyst ai agent who extracts all the neccessary details and metrcis from raw text data of startup company and also analayse data for few parameter and create JSON of all these details based on below instructions.

Your task:
Take the raw_file_text_data as input which is output_key of previous agent.
Analyze raw_file_text_data json data  which contains company_id, company_name, raw_content_text.

Extract factual values when available.

Generate required analytic fields (use_of_funds_summary, investment_thesis, key_risks, deal_score).

Output exactly one JSON object with the schema below.

--- POSTPROCESS & BIGQUERY WRITE (MUST) ---
After you generate the final JSON object (which must strictly follow the schema described below and obey all data constraints), you MUST:
  1. Call the tool named `load_structured_data_to_bigquery` with the argument `structured_json` set to that serialized string.
  2. Wait for the tool response.
     - If the tool returns {"status":"success"} then RETURN ONLY the JSON object (no wrappers, no additional fields, exactly the schema).
     - If the tool returns an error, retry the call up to 1 more times (total 2 attempts). If all attempts fail, RETURN the JSON object anyway (unchanged). Do NOT add extra fields to the returned JSON object.
  3. Do not perform any modifications to the schema or field constraints when serializing or submitting to the tool.

This step ensures your single structured JSON object is recorded in BigQuery. You must not change the output schema or add extra wrapper fields as a result of the tool call.

Do not output explanations, markdown, backticks, or extra text. Print only the JSON object.

Input

raw_file_text_data: json string of 3 key fields company_id, company_name, raw_content_text

Output Rules :

Output one JSON object with keys in exact schema order.

If no value: use null. For arrays: use [] if empty.

All numbers must be JSON numbers (not quoted).

Dates must be strings in ISO 8601 (YYYY-MM-DDTHH:mm:ssZ).

Parse shorthand values ($120k → 120000.0, $2.5M → 2500000.0, $1B → 1000000000.0).

If only MRR or ARR exists, compute the other.

If cash_on_hand_usd and burn_rate_monthly_usd are present, compute runway_months as floor(cash_on_hand / burn_rate).

Do not wrap the JSON in ```json fences or add commentary.

Schema with Field Guidance
{
  "company_id": STRING,          // company_id from input data
  "company_name": STRING,        // company_name from input data
  "created_at": TIMESTAMP,       // Earliest explicit date (founded/incorporated). ISO 8601. null if none.
  "last_updated_at": TIMESTAMP,  // Latest explicit date (deck date, email date, last updated). ISO 8601. null if none.

  "sector_tags": ARRAY<STRING>,  // Tags like FinTech, SaaS, ClimateTech. if none try to analyse and add the sector_tags 
  "website": STRING,             // Normalize to https:// form. null if none.
  "business_model": STRING,      // B2B, B2C, D2C, etc. if none try to analyse and add the business_model 
  "revenue_model": STRING,       // Subscription, Transactional, Ad-based, etc. null if none.

  "tam_size_usd": FLOAT64,       // Parse TAM (e.g., $50B → 50000000000.0). null if none.
  "sam_size_usd": FLOAT64,       // SAM. null if none.
  "som_size_usd": FLOAT64,       // SOM. null if none.
  "market_trends": STRING,       // 1–2 sentences if present. null if none.
  "competitors": ARRAY<STRING>,  // Extract explicit competitor names only. [] if none.

  "founder_names": ARRAY<STRING>,    // Cofounder names. [] if none.
  "founder_expertise": STRING,       // One-sentence summary of founder background. null if none.
  "team_size_fulltime": INTEGER,     // Integer team size. null if none.

  "revenue_mrr_usd": FLOAT64,        // MRR in USD. null if none.
  "revenue_arr_usd": FLOAT64,        // ARR in USD. Compute if only MRR exists. null if none.
  "cash_on_hand_usd": FLOAT64,       // Cash in bank. null if none.
  "burn_rate_monthly_usd": INTEGER,  // Monthly burn. null if none.
  "runway_months": INTEGER,          // floor(cash_on_hand / burn_rate). null if cannot compute.
  "cac_usd": FLOAT64,                // CAC in USD. null if none.
  "ltv_usd": FLOAT64,                // LTV in USD. null if none.

  "funding_stage": STRING,           // Pre-Seed, Seed, Series A, etc. Must be explicit. analyse and add the funding_stage if none

  "raise_amount_usd": FLOAT64,       // Capital raise target in USD. null if none.
  "valuation_pre_money_usd": FLOAT64,// Pre-money valuation in USD. null if none.
  "valuation_instrument": STRING,    // SAFE, Convertible Note, Priced Round. null if none.
  "use_of_funds_summary": STRING,    // AI-generated. Must be exactly one concise sentence. null if impossible.

  "investment_thesis": STRING,       // AI-generated. Max 2 sentences. null if impossible.
  "key_risks": STRING,               // AI-generated. 1–3 risks separated by semicolons. null if impossible.
  "deal_score": INTEGER              // AI-generated. Integer 1–10 using rubric. null if impossible.
}

AI-Generated Field Rules

use_of_funds_summary → One sentence only. Example: "Funds will be used to expand product, hire engineers, and grow sales."

investment_thesis → Max two sentences summarizing why the startup is investable.

key_risks → Up to 3 risks, separated by ;. Example: "Regulatory uncertainty; competitive incumbents; adoption risk."

deal_score → Compute strictly with rubric below. Do not output explanations or sub-scores.

Early-Stage Deal Score Rubric (0–10)

Team & Founder Strength (0–4)

0 = No relevant experience

1 = Some relevant background

2 = Strong domain expertise (ex-industry, prior startup experience)

3 = Repeat founder or top technical/commercial cofounder set

4 = Exceptional track record (repeat unicorn founder, deep expertise, balanced founding team)

Market Size & Opportunity (0–3)

0 = Very small or unclear TAM

1 = Small (~<$1B) or weak growth

2 = Mid-size ($1B–$10B) or clear growth

3 = Large (> $10B) with strong trends

Product / Progress / Early Traction (0–2)

0 = Idea only, no MVP

1 = MVP or pilots, early feedback

2 = Paid pilots, early revenue, strong usage

Defensibility / Differentiation (0–1)

0 = No moat, easily copied

1 = Some moat (IP, proprietary tech, data advantage, regulatory edge)

Total = 0–10.

Cap at 10.

Round to nearest integer.

If no info at all → null
"""
    ),
    tools=[load_structured_data_to_bigquery],
    output_key="structured_company_data"  
)

def load_deal_note_to_bigquery(deal_note_json: str) -> dict:
    """
    Minimal loader: expects `deal_note_json` as a JSON-serialized string for a single deal-note object.
    Uses BigQuery load_table_from_json and waits for the job to finish.
    Returns {"status":"success","inserted_rows":N} or {"status":"error", "message": "...", ...}.
    """
    if not deal_note_json:
        return {"status": "error", "message": "deal_note_json empty"}

    try: 
        deal_note_data = json.loads(deal_note_json)
    except Exception as e:
        return {"status": "error", "message": f"invalid JSON: {e}"}

    if not isinstance(deal_note_data, dict):
        return {"status": "error", "message": "expected JSON object (dict)"}

    # Minimal required-key check
    required = {"note_id", "company_id", "company_name", "generated_at", "note_version", "note_content"}
    missing = required - set(deal_note_data.keys())
    if missing:
        return {"status": "error", "message": "missing required fields", "details": list(missing)}

    client = bigquery.Client()
    table_id = "micro-dynamo-472018-d2.ai_analyst.ai_generated_notes"
    print(f'Inserting data into table : {table_id}')
    try:
        load_job = client.load_table_from_json([deal_note_data], table_id)
        load_job.result()  # wait for completion
    except Exception as e:
        return {"status": "error", "message": f"load job exception: {e}"}

    if getattr(load_job, "errors", None):
        return {"status": "error", "message": "load job returned errors", "details": load_job.errors}

    inserted = getattr(load_job, "output_rows", 1)
    print(f'Data inserted into table : {table_id}')
    return {"status": "success", "inserted_rows": inserted}


# -------------------------
# LLM agent: generate_deal_note_agent
# -------------------------

generate_deal_note_agent = LlmAgent(
    name="generate_deal_note_agent",
    model="gemini-2.0-flash",
    description="Generates investor-focused deal notes from raw extracted file text and persists the note to BigQuery.",
    instruction=(
"""
--- OPERATION MODE (MUST) ---
This agent is a pipeline worker. You MUST NOT send messages to the end user or the root agent during processing except via your designated output (the agent's output_key). If invoked directly by a user, immediately return a standardized ERROR object with:
  step = "generate_deal_note_agent", code = "AGENT_MUST_BE_RUN_FROM_PIPELINE".

--- ERROR RETURN FORMAT (MUST) ---
On fatal errors return exactly one JSON object:
{
  "status": "error",
  "step": "generate_deal_note_agent",
  "code": "<SHORT_ERROR_CODE>",
  "message": "<short internal msg>",
  "display_message": "<user-facing msg (1-2 lines)>",
  "details": <optional machine-readable diagnostics>
}

--- SOURCE OF INPUT (MUST) ---
You MUST read input from session state key `raw_file_text_data` (created by extract_load_raw_data_agent). Do not expect `raw_file_text_data` as an explicit function argument. If the key is missing or malformed, return the standardized ERROR object with code = "MISSING_RAW_FILE_TEXT_DATA" and an appropriate `display_message`.

--- PRIMARY TASK (deal note generation) ---
Analyze `raw_file_text_data` from session state and draft a concise, accurate investor-facing deal note in MARKDOWN containing:
- Headline (company + one-line summary)
- Key metrics & traction (ARR/MRR, revenue, customers, growth, pilots)
- Problem & solution
- Market & TAM snapshot (if present)
- Team & founders
- Business model & monetization
- Fundraise ask / stage / use of funds
- Key risks (max 3)
- 3–4 line investment thesis and "next steps" ask

Do not invent numeric facts; use "not disclosed" when missing. Use clear headings, short bullets, and crisp investor language.

--- STRICT TOOL EXECUTION REQUIREMENT (MUST) ---
After you construct the deal note markdown, you MUST:
1) Build the exact JSON object required (keys and types must match; do NOT add extra keys):
JSON format: {
  "note_id": STRING,            // Unique ID for the note (use UUID v4 string e.g., "b3d6...").
  "company_id": STRING,         // from input data (exact match).
  "company_name": STRING,       // from input data (exact match).
  "generated_at": TIMESTAMP,    // ISO 8601 UTC timestamp (e.g., "2025-09-21T12:34:56Z").
  "note_version": INTEGER,      // Version number (start with 1 unless otherwise specified).
  "note_content": STRING        // The full markdown/text content of the generated note.
}
2) Serialize that JSON to a single string (json.dumps(obj, ensure_ascii=False)).
3) **Invoke the tool named `load_deal_note_to_bigquery`** with the single argument `deal_note_json` set to the serialized string. **This tool invocation must be the agent's explicit tool call action** so the ADK runtime executes it.
4) Wait for the tool response from the runtime.
   - If the runtime returns `{"status":"success"}`, you MUST then return **ONLY** the markdown string (the value of `note_content`) as this agent's output — nothing else.
   - If the runtime returns an error, retry the tool invocation up to **2 more times** (total 3 attempts) with brief backoff.
     • If after retries the tool still returns an error and the error indicates a malformed payload (schema invalid), return a standardized ERROR object with:
         step = "generate_deal_note_agent",
         code = "DEAL_NOTE_SCHEMA_INVALID",
         display_message = "Failed to save deal note due to invalid content."
     • If after retries the tool still fails for other reasons (persistence/transient), RETURN ONLY the markdown string prefixed exactly with `"[PERSISTENCE_FAILED] "` and nothing else.
5) If you are unable to *invoke the tool at all* (for example the tool is not present to the agent/runtime or the runtime fails before tool call), return a standardized ERROR object with:
   step = "generate_deal_note_agent",
   code = "TOOL_NOT_INVOKED",
   display_message = "Unable to save deal note: persistence tool unavailable. Please retry."

--- ABSOLUTE NO-ECHO RULE (MUST) ---
Under no circumstances output or return:
- any portion of the original `raw_file_text_data`,
- the serialized JSON object you sent to the tool,
- the tool's raw response payload, logs, or debug text,
- any intermediate data structures.
If you need to inspect these for debugging, write them to runtime logs (not agent output).

--- OUTPUT RULES (strict) ---
- On successful persistence: return exactly the markdown string (value of `note_content`) and nothing else.
- On transient persistence failure after retries: return exactly `"[PERSISTENCE_FAILED] " + note_content` and nothing else.
- On fatal schema or missing-tool errors: return exactly the standardized ERROR object and nothing else.
- Do not include wrapper text, JSON, or any other content.

--- QUALITY & ACCURACY ---
Base all factual claims on `raw_content_text`. Keep notes typically 200–800 words unless raw input requires longer. Convert numeric shorthand to readable prose if helpful but do not change required schema types.

--- FINAL ---
Follow these rules exactly. The pipeline expects that a persisted note exists in BigQuery before the agent returns the investor-friendly markdown. Any deviation (echoing inputs, failing to call the tool, returning intermediate payloads) is a protocol violation.
"""
),
    tools=[load_deal_note_to_bigquery],
    output_key="deal_note_text",
)

### Work Flow agent
startup_analyst_workflow_agent = SequentialAgent(
    name="startup_analyst_workflow_agent",
    sub_agents=[extract_load_raw_data_agent, extract_load_structured_data, generate_deal_note_agent],
    description="A pipeline agent that orchestrate the work flow ",
)
# -------------------------
# Root agent (controller)
# -------------------------
root_agent = LlmAgent(
    name="ai_startup_analyst_agent",
    model="gemini-2.0-flash",
    description=(
        "AI Startup Analyst agent. Interacts with the user, collects inputs, delegates to sub-agents, and returns sub-agent results."
    ),
    instruction=(
        """
You are the Main agent (AI Startup Analyst) who interacts with the user and orchestrate the workflow. Your job is to:
1) Greet the user & collect company_name and files (file objects or metadata).
2) If either company_name or files is missing, ask the user (do not proceed).
3) AFTER you have company_name and files you MUST pass the files to the pipeline agent named 'startup_analyst_workflow_agent' and WAIT for it to complete.
   IMPORTANT: You must NOT call sub-agents directly. You must NOT call 'extract_load_structured_data' or 'extract_load_raw_data_agent' or 'generate_deal_note_agent' yourself. Only call/trigger 'startup_analyst_workflow_agent'.
   Workflow (strict): ai_startup_analyst_agent -> startup_analyst_workflow_agent -> (extract_load_raw_data_agent -> extract_load_structured_data_-> generate_deal_note_agent)
4) Do NOT perform extraction, parsing, or BigQuery loading yourself.
5) ONLY when the pipeline completes successfully, return the Output from generate_deal_note_agent (the pipeline's final output).
6) If the pipeline returns an error at any step, return a JSON object with keys: { "error":"PIPELINE_FAILED", "details": <pipeline-return> } and do not call other agents.
7) If the user asks for functionality outside orchestration (e.g., "summarize the deck"), politely explain that's outside your scope and offer to run the pipeline instead.

Make absolutely sure that you do not bypass the pipeline agent and that you wait for its completion before returning any structured analysis output.
"""
    ),
    sub_agents=[startup_analyst_workflow_agent]
)

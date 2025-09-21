CREATE TABLE `micro-dynamo-472018-d2.ai_analyst.companies` (
    -- Primary Key & Metadata
    company_id STRING OPTIONS(description="Unique ID for each company."),
    company_name STRING OPTIONS(description="The startup's name."),
    created_at TIMESTAMP OPTIONS(description="The timestamp the company was first logged."),
    last_updated_at TIMESTAMP OPTIONS(description="The timestamp the record was last updated."),

    -- Core Business & Product Details
    sector_tags ARRAY<STRING> OPTIONS(description="Tags like 'FinTech', 'SaaS', etc."),
    website STRING OPTIONS(description="Startup's official website."),
    business_model STRING OPTIONS(description="B2B, B2C, D2C, etc."),
    revenue_model STRING OPTIONS(description="Subscription, transactional, ad-based, etc."),
    
    -- Market Opportunity
    tam_size_usd FLOAT64 OPTIONS(description="Total Addressable Market in USD."),
    sam_size_usd FLOAT64 OPTIONS(description="Serviceable Addressable Market in USD."),
    som_size_usd FLOAT64 OPTIONS(description="Serviceable Obtainable Market in USD."),
    market_trends STRING OPTIONS(description="Qualitative summary of market trends."),
    competitors ARRAY<STRING> OPTIONS(description="List of key competitors."),

    -- Team & Founder Details
    founder_names ARRAY<STRING> OPTIONS(description="List of co-founder names."),
    founder_expertise STRING OPTIONS(description="Summary of founder's relevant expertise."),
    team_size_fulltime INTEGER OPTIONS(description="Number of full-time employees."),

    -- Financials & Traction
    revenue_mrr_usd FLOAT64 OPTIONS(description="Current Monthly Recurring Revenue."),
    revenue_arr_usd FLOAT64 OPTIONS(description="Current Annual Recurring Revenue."),
    cash_on_hand_usd FLOAT64 OPTIONS(description="Current cash in the bank."),
    burn_rate_monthly_usd INTEGER OPTIONS(description="Monthly cash burn rate."),
    runway_months INTEGER OPTIONS(description="Calculated runway in months."),
    cac_usd FLOAT64 OPTIONS(description="Customer Acquisition Cost."),
    ltv_usd FLOAT64 OPTIONS(description="Customer Lifetime Value."),

    -- The Deal & Investment
    funding_stage STRING OPTIONS(description="Pre-Seed, Seed, Series A, etc."),
    raise_amount_usd FLOAT64 OPTIONS(description="Total capital being raised."),
    valuation_pre_money_usd FLOAT64 OPTIONS(description="Pre-money valuation."),
    valuation_instrument STRING OPTIONS(description="SAFE, Convertible Note, Priced Round."),
    use_of_funds_summary STRING OPTIONS(description="How funds will be used."),

    -- AI-generated Analysis & Scores
    investment_thesis STRING OPTIONS(description="AI-generated summary of the investment case."),
    key_risks STRING OPTIONS(description="AI-generated summary of risks and mitigations."),
    deal_score INTEGER OPTIONS(description="AI-assigned score (e.g., 1-10).")
);


CREATE TABLE `micro-dynamo-472018-d2.ai_analyst.raw_data` (
    source_id STRING OPTIONS(description="Unique ID for each source document."),
    company_id STRING OPTIONS(description="Links to the main companies table."),
	company_name STRING OPTIONS(description="The startup's name."),
    source_type STRING OPTIONS(description="e.g., 'pitch_deck', 'email', 'call_transcript', 'founder_checklist'."),
    received_at TIMESTAMP OPTIONS(description="Timestamp when the document was received."),
    file_name STRING OPTIONS(description="Original file name."),
    raw_content_text STRING OPTIONS(description="The full raw text content of the document.")
);

CREATE TABLE `micro-dynamo-472018-d2.ai_analyst.ai_generated_notes` (
    note_id STRING OPTIONS(description="Unique ID for each generated note."),
    company_id STRING OPTIONS(description="Links to the main companies table."),
	company_name STRING OPTIONS(description="The startup's name."),
    generated_at TIMESTAMP OPTIONS(description="Timestamp of note generation."),
    note_version INTEGER OPTIONS(description="Version number for the deal note (e.g., 1, 2, 3...)."),
    note_content STRING OPTIONS(description="The full markdown or text content of the generated note.")
);

"""
Doppelganger Engine - Main Application

This Flask application serves as a backend service that finds demographic "doppelgangers"
for US ZIP codes. It fetches census data, analyzes it using Google's Gemini AI,
and returns similar ZIP codes with detailed demographic profiles.

The service processes requests from the doppelganger-api Node.js application,
fetching demographic data from the US Census Bureau API and generating insights
using Google's Generative AI models.
"""

import os
import logging
import json
import requests  # Required for making HTTP requests to the Census API
from flask import Flask, jsonify, request  # Flask web framework for API endpoints
from flask_cors import CORS
import google.generativeai as genai  # Google's Generative AI SDK for Gemini models
from google.cloud import firestore  # --- NEW: Added for Firestore Caching ---

# --- Configuration and Environment Setup ---
# Retrieve the Gemini API key from environment variables.
# This key is required for authenticating requests to Google's Generative AI service.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Validate that the API key is present before proceeding.
# Without this key, the application cannot function, so we raise an error immediately.
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set.")

# Configure the Generative AI library with the API key.
# This global configuration allows us to use genai models throughout the application.
try:
    genai.configure(api_key=GEMINI_API_KEY)
except Exception as e:
    # Log the error for debugging purposes before re-raising.
    # This ensures the application fails fast if configuration fails.
    logging.error(f"Error initializing GenerativeModel: {e}")
    raise

# --- NEW: Initialize Firestore Client ---
# Create a global Firestore client.
# By default, firestore.Client() will use the service account
# permissions of the Cloud Run environment it's running in.
# We will wrap this in a try/except so the app can still run
# (without caching) if Firestore permissions are missing.
try:
    db = firestore.Client()
    logging.info("Firestore client initialized successfully.")
except Exception as e:
    logging.error(f"Error initializing Firestore client: {e}")
    db = None  # Set db to None so we can check its existence later

# --- Helper Functions: Data Formatting Utilities ---
# These functions format numeric values for display in prompts and responses.
# They are ported from the TypeScript formatters to maintain consistency
# across the frontend and backend formatting logic.

def format_currency(value):
    """
    Format a numeric value as US currency with dollar sign and thousands separators.
    
    Args:
        value (float): The numeric value to format as currency.
    
    Returns:
        str: Formatted string in the format "$X,XXX" (e.g., "$45,000").
        
    Example:
        >>> format_currency(45000)
        '$45,000'
    """
    # Format with comma thousands separator and no decimal places
    return f"${value:,.0f}"

def format_number(value):
    """
    Format a numeric value with thousands separators for readability.
    
    Args:
        value (int): The numeric value to format.
    
    Returns:
        str: Formatted string with comma separators (e.g., "1,234,567").
        
    Example:
        >>> format_number(1234567)
        '1,234,567'
    """
    # Use comma as thousands separator
    return f"{value:,}"

def format_percent(value):
    """
    Format a numeric value as a percentage with one decimal place.
    
    Args:
        value (float): The numeric value to format as a percentage.
    
    Returns:
        str: Formatted string with one decimal place and percent sign (e.g., "45.3%").
        
    Example:
        >>> format_percent(45.333)
        '45.3%'
    """
    # Format with one decimal place followed by percent sign
    return f"{value:.1f}%"

# --- Census API Integration: Demographic Data Fetching ---
def fetch_census_demographics(zip_code):
    """
    Fetches comprehensive demographic data from the US Census Bureau's American
    Community Survey (ACS) 5-Year Estimates API for a given ZIP code.
    
    This function queries the Census API for demographic variables including:
    - Population demographics (age, race, gender)
    - Economic indicators (median income, home values, rent)
    - Education levels
    - Housing characteristics (ownership, occupancy)
    - Commuting patterns (work from home, public transit)
    
    This is a Python port of the TypeScript 'fetchCensusDemographics' function
    to maintain consistency across the application stack.
    
    Args:
        zip_code (str): The 5-digit US ZIP code for which to fetch demographic data.
    
    Returns:
        dict: A dictionary containing structured demographic data, or None if:
            - The ZIP code is invalid or not found
            - The API request fails
            - The response data cannot be parsed
    
    Raises:
        requests.exceptions.RequestException: If the HTTP request to the Census API fails.
        Exception: For any other unexpected errors during data processing.
        
    Example:
        >>> demographics = fetch_census_demographics("90210")
        >>> demographics['population']
        20575
    """
    logging.info(f"Fetching Census data for ZIP: {zip_code}")
    
    # Define the Census ACS variable codes we need to fetch.
    # These codes correspond to specific demographic questions in the American
    # Community Survey. Each variable represents a specific data point:
    # - NAME: Geographic area name
    # - B01003_001E: Total population
    # - B01002_001E: Median age
    # - B09001_001E: Population under 18
    # - B01001_020E through B01001_025E: Male population aged 65-85+ (6 age groups)
    # - B01001_044E through B01001_049E: Female population aged 65-85+ (6 age groups)
    # - B19013_001E: Median household income
    # - B25077_001E: Median home value
    # - B25064_001E: Median gross rent
    # - B02001_002E through B02001_005E: Race categories (White, Black, Native, Asian)
    # - B15003_001E: Total population 25+ for education
    # - B15003_022E through B15003_025E: Education levels (Bachelor's, Master's, Professional, Doctorate)
    # - B25002_001E through B25002_003E: Housing occupancy (total, owner, renter)
    # - B08301_001E, B08301_002E, B08301_010E, B08301_021E: Commuting data (total, drive, public transit, work from home)
    variables = [
      'NAME', 'B01003_001E', 'B01002_001E', 'B09001_001E', 'B01001_020E', 
      'B01001_021E', 'B01001_022E', 'B01001_023E', 'B01001_024E', 'B01001_025E',
      'B01001_044E', 'B01001_045E', 'B01001_046E', 'B01001_047E', 'B01001_048E', 
      'B01001_049E', 'B19013_001E', 'B25077_001E', 'B25064_001E', 'B02001_002E', 
      'B02001_003E', 'B02001_004E', 'B02001_005E', 'B15003_001E', 'B15003_022E', 
      'B15003_023E', 'B15003_024E', 'B15003_025E', 'B25002_001E', 'B25002_002E', 
      'B25002_003E', 'B08301_001E', 'B08301_002E', 'B08301_010E', 'B08301_021E',
    ]
    
    # Join the variable codes into a comma-separated string for the API query.
    # The Census API accepts multiple variables as a comma-separated list.
    variables_str = ",".join(variables)
    
    # Construct the Census API URL for the 2022 ACS 5-Year Estimates dataset.
    # The URL format is: base_url?get=variables&for=geography:identifier
    # We use "zip code tabulation area" as the geography type to query by ZIP code.
    # The zip_code is URL-encoded in the query string.
    census_url = f"https://api.census.gov/data/2022/acs/acs5?get={variables_str}&for=zip%20code%20tabulation%20area:{zip_code}"

    try:
        # Make HTTP GET request to the Census API.
        # The requests library handles URL encoding and connection management.
        response = requests.get(census_url)
        
        # Raise an exception for HTTP error status codes (4xx client errors, 5xx server errors).
        # This ensures we catch API errors early rather than processing invalid data.
        response.raise_for_status()
        
        # Parse the JSON response from the Census API.
        # The Census API returns data as a JSON array where:
        # - The first element is an array of column headers (variable names)
        # - Subsequent elements are arrays of values corresponding to those headers
        data = response.json()

        # Validate that we received valid data structure.
        # The Census API should return at least 2 rows: headers and one data row.
        # If the ZIP code is invalid or has no data, the response may be empty or malformed.
        if not data or len(data) < 2:
            logging.warning(f"No Census data found for ZIP: {zip_code}")
            return None

        # Extract the header row (first element) which contains the variable names.
        # This maps to the column indices in the data rows.
        headers = data[0]
        
        # Extract the first (and typically only) data row for this ZIP code.
        # The values array contains the demographic values in the same order as headers.
        values = data[1]

        # --- Nested Helper Functions for Data Extraction ---
        # These functions safely extract values from the Census API response,
        # handling cases where variables might be missing or have invalid values.
        
        def get_value(field_name):
            """
            Safely extract an integer value from the Census API response.
            
            This function looks up a field by name in the headers array,
            finds its corresponding value in the values array, and converts
            it to an integer. If the field is missing or the value is invalid,
            it returns 0 as a safe default.
            
            Args:
                field_name (str): The Census variable code (e.g., 'B01003_001E').
            
            Returns:
                int: The integer value for the field, or 0 if not found/invalid.
            """
            try:
                # Find the index of the field name in the headers array.
                index = headers.index(field_name)
                # Retrieve the corresponding value and convert to integer.
                # Census API returns numeric values as strings, so we parse them.
                return int(values[index])
            except (ValueError, IndexError, TypeError):
                # Handle cases where:
                # - ValueError: field_name not found in headers, or value cannot be converted to int
                # - IndexError: index is out of bounds (shouldn't happen, but defensive)
                # - TypeError: values[index] is None or wrong type
                return 0
        
        def get_string_value(field_name):
            """
            Safely extract a string value from the Census API response.
            
            Similar to get_value, but preserves the value as a string.
            Used for fields like geographic names that should remain as strings.
            
            Args:
                field_name (str): The Census variable code (e.g., 'NAME').
            
            Returns:
                str: The string value for the field, or empty string if not found.
            """
            try:
                # Find the index of the field name in the headers array.
                index = headers.index(field_name)
                # Retrieve the corresponding value as a string.
                return values[index]
            except (ValueError, IndexError, TypeError):
                # Return empty string if field is missing or invalid.
                return ""
        
        # --- Demographic Data Calculation and Aggregation ---
        # Extract and calculate demographic metrics from the Census API response.
        # Some metrics require aggregating multiple Census variables.
        
        # Total population: Direct value from Census API.
        total_population = get_value('B01003_001E')
        
        # Population under 18: Direct value from Census API.
        age_under_18 = get_value('B09001_001E')
        
        # Population 65 and older: Sum of multiple age group variables.
        # The Census API breaks down the 65+ population into multiple age groups
        # by gender. We sum all these groups to get the total 65+ population.
        # Variables B01001_020E through B01001_025E are males aged 65-85+
        # Variables B01001_044E through B01001_049E are females aged 65-85+
        age_65_plus = sum([
            get_value(key) for key in [
                'B01001_020E', 'B01001_021E', 'B01001_022E', 'B01001_023E', 'B01001_024E', 'B01001_025E',
                'B01001_044E', 'B01001_045E', 'B01001_046E', 'B01001_047E', 'B01001_048E', 'B01001_049E'
            ]
        ])
        
        # Population aged 18-64: Calculated as total population minus other age groups.
        # This is the working-age population that is neither children nor seniors.
        age_18_to_64 = total_population - age_under_18 - age_65_plus
        
        # Graduate education: Sum of Master's, Professional, and Doctorate degrees.
        # These represent advanced degrees beyond a Bachelor's degree.
        # B15003_023E: Master's degree
        # B15003_024E: Professional degree
        # B15003_025E: Doctorate degree
        education_graduate = get_value('B15003_023E') + get_value('B15003_024E') + get_value('B15003_025E')

        # --- Build Structured Demographics Dictionary ---
        # Construct a dictionary containing all demographic data in a structured format.
        # This dictionary is used by downstream functions for analysis and AI processing.
        # The field names match the TypeScript interface to maintain API consistency.
        demographics = {
            # Geographic identifier: Name of the ZIP code tabulation area.
            "name": get_string_value('NAME'),
            
            # Population metrics: Total population count.
            "population": total_population,
            
            # Economic indicators: Median household income in dollars.
            "medianIncome": get_value('B19013_001E'),
            
            # Age metrics: Median age of the population (may be a decimal).
            # Convert to float to handle decimal ages, defaulting to 0 if missing.
            "medianAge": float(get_string_value('B01002_001E') or 0),
            
            # Racial composition: Counts of population by race categories.
            # These represent the number of people who identify with each race category.
            # Note: The Census allows multiple race selections, so these may not sum to total.
            "raceWhite": get_value('B02001_002E'),      # White alone
            "raceBlack": get_value('B02001_003E'),      # Black or African American alone
            "raceNative": get_value('B02001_004E'),     # American Indian and Alaska Native alone
            "raceAsian": get_value('B02001_005E'),      # Asian alone
            
            # Education metrics: Population 25 years and older with education data.
            "educationPopulation": get_value('B15003_001E'),  # Total population 25+ for education
            "educationBachelors": get_value('B15003_022E'),   # Bachelor's degree holders
            "educationGraduate": education_graduate,          # Advanced degree holders (calculated above)
            
            # Housing metrics: Median home value and rent in dollars.
            "medianHomeValue": get_value('B25077_001E'),  # Median value of owner-occupied housing
            "medianRent": get_value('B25064_001E'),       # Median gross rent
            
            # Housing occupancy: Counts of housing units by occupancy type.
            "housingUnits": get_value('B25002_001E'),     # Total housing units
            "ownerOccupied": get_value('B25002_002E'),    # Owner-occupied housing units
            "renterOccupied": get_value('B25002_003E'),   # Renter-occupied housing units
            
            # Age distribution: Population counts by age groups (calculated above).
            "ageUnder18": age_under_18,      # Population under 18 years
            "age18to64": age_18_to_64,       # Population aged 18-64 years
            "age65plus": age_65_plus,        # Population aged 65 and older
            
            # Commuting patterns: Worker counts by mode of transportation.
            "commuteTotal": get_value('B08301_001E'),   # Total workers 16+ who commute
            "commuteDrive": get_value('B08301_002E'),   # Workers who drive alone
            "commutePublic": get_value('B08301_010E'),  # Workers using public transportation
            "commuteWfh": get_value('B08301_021E'),    # Workers who work from home
            
            # ZIP code: Use the value from Census API if available, otherwise use input.
            # The Census API returns this as "zip code tabulation area" in the response.
            "zipCode": get_string_value('zip code tabulation area') or zip_code,
        }
        
        # Return the complete demographics dictionary for use by downstream functions.
        return demographics

    except requests.exceptions.RequestException as e:
        # Handle HTTP-related errors from the Census API request.
        # This includes network errors, timeouts, and HTTP error status codes.
        # Log the error for debugging and return None to indicate failure.
        logging.error(f"Error fetching Census data: {e}")
        return None
    except Exception as e:
        # Handle any other unexpected errors during data processing.
        # This is a catch-all for errors in JSON parsing, data extraction, or calculations.
        # Log the error for debugging and return None to indicate failure.
        logging.error(f"Error processing Census data: {e}")
        return None

# --- Gemini AI Integration: Community Profile Generation ---
def get_gemini_profile(data):
    """
    Generates a detailed, qualitative community profile using Google's Gemini AI
    based on demographic data for a given ZIP code.
    
    This function uses Google's Generative AI to analyze census demographic data
    and create a narrative description of the community. The AI generates insights
    about the area's character, lifestyle, neighborhood characteristics, and
    socioeconomic traits in a market research analyst persona.
    
    This is a Python port of the TypeScript 'getGeminiProfile' function from
    geminiHelper.ts to maintain consistency across the application stack.
    
    Args:
        data (dict): A dictionary containing demographic data for a ZIP code.
            Expected keys include: zipCode, population, medianAge, medianIncome,
            medianHomeValue, medianRent, ageUnder18, age65plus, ownerOccupied,
            housingUnits, educationBachelors, educationGraduate, educationPopulation,
            commuteTotal, commuteWfh, raceWhite, raceBlack, raceAsian.
    
    Returns:
        dict: A JSON object containing:
            - whoAreWe (str): Narrative paragraph describing the area's character
            - ourNeighborhood (list[str]): 3-5 key facts about the neighborhood
            - socioeconomicTraits (list[str]): 3-5 key facts about socioeconomic status
            - OR {"error": str} if the AI generation fails
    
    Raises:
        Exception: If the Gemini API call fails or response cannot be parsed.
        
    Example:
        >>> demographics = fetch_census_demographics("90210")
        >>> profile = get_gemini_profile(demographics)
        >>> profile['whoAreWe']
        'Beverly Hills is an affluent community...'
    """
    logging.info(f"Generating Gemini profile for ZIP: {data['zipCode']}")
    
    # --- Calculate Derived Metrics for Prompt ---
    # Convert raw counts to percentages for more meaningful analysis.
    # These percentages provide context about the relative composition of the population.
    
    # Higher education percentage: Proportion of adults (25+) with Bachelor's or higher.
    # This is a key indicator of educational attainment and economic potential.
    # Avoid division by zero by checking if the denominator is greater than 0.
    higher_ed_percent = (
        (data['educationBachelors'] + data['educationGraduate']) / 
        data['educationPopulation'] * 100 
        if data['educationPopulation'] > 0 else 0
    )
    
    # Owner-occupied housing percentage: Proportion of housing units that are owner-occupied.
    # This indicates the stability and investment level of the community.
    owner_occupied_percent = (
        data['ownerOccupied'] / data['housingUnits'] * 100 
        if data['housingUnits'] > 0 else 0
    )
    
    # Work-from-home percentage: Proportion of workers who work from home.
    # This is a modern indicator of remote work adoption and lifestyle flexibility.
    wfh_percent = (
        data['commuteWfh'] / data['commuteTotal'] * 100 
        if data['commuteTotal'] > 0 else 0
    )
    
    # Age distribution percentages: Proportion of population in different age groups.
    # These help characterize the community's life stage and demographic profile.
    age_under_18_percent = (
        data['ageUnder18'] / data['population'] * 100 
        if data['population'] > 0 else 0
    )
    age_65_plus_percent = (
        data['age65plus'] / data['population'] * 100 
        if data['population'] > 0 else 0
    )

    # --- Construct AI Prompt ---
    # Build a detailed prompt for the Gemini AI model that includes:
    # - Context about the task (community profile generation)
    # - Persona instructions (market research analyst)
    # - Formatted demographic data for analysis
    # - Output format requirements (JSON schema)
    # 
    # The prompt is designed to guide the AI to generate insightful, professional
    # descriptions that would be useful for businesses or people considering moving.
    prompt = f"""
    Analyze the following demographic data for ZIP code {data['zipCode']} to create a detailed community profile.
    Generate a response in the persona of a market research analyst describing the area to a business or someone considering moving there.
    The response must be structured as a JSON object that adheres to the provided schema.
    
    Data for Analysis:
    - Total Population: {format_number(data['population'])}
    - Median Age: {data['medianAge']:.1f} years
    - Age Distribution: {format_percent(age_under_18_percent)} under 18, {format_percent(age_65_plus_percent)} 65+
    - Median Household Income: {format_currency(data['medianIncome'])}
    - Median Home Value: {format_currency(data['medianHomeValue'])}
    - Median Rent: {format_currency(data['medianRent'])}
    - Housing Occupancy: {format_percent(owner_occupied_percent)} owner-occupied
    - Education: {format_percent(higher_ed_percent)} of adults (25+) have a Bachelor's degree or higher
    - Commute: {format_percent(wfh_percent)} of workers work from home
    - Racial Composition: Population is approximately {format_number(data['raceWhite'])} White, {format_number(data['raceBlack'])} Black, and {format_number(data['raceAsian'])} Asian.
    """

    # --- Define JSON Schema for AI Response ---
    # Specify the expected structure of the AI-generated response using JSON Schema.
    # This ensures the AI returns data in a consistent, parseable format.
    # The schema is a Python translation of the TypeScript insightResponseSchema.
    schema = {
        "type": "object",
        "properties": {
            "whoAreWe": {
                "type": "string",
                "description": "A narrative paragraph summarizing the area's character, lifestyle, and key traits of the population."
            },
            "ourNeighborhood": {
                "type": "array",
                "description": "A list of 3-5 key facts about the neighborhood, focusing on housing, density, and household composition.",
                "items": {"type": "string"}
            },
            "socioeconomicTraits": {
                "type": "array",
                "description": "A list of 3-5 key facts about the population's socioeconomic status, including education, employment, and financial habits.",
                "items": {"type": "string"}
            }
        },
        "required": ["whoAreWe", "ourNeighborhood", "socioeconomicTraits"]
    }

    try:
        # Initialize the Gemini Generative Model.
        # We use 'gemini-2.5-flash' which is a fast, efficient model suitable for
        # structured data generation tasks like this community profile.
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # Generate content using the Gemini AI model.
        # The generation_config specifies:
        # - response_mime_type: Forces the response to be JSON format
        # - response_schema: Validates the response structure matches our schema
        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": schema
            }
        )
        
        # Parse the JSON response from the AI model.
        # The response.text contains the JSON string that we need to parse.
        return json.loads(response.text)
    except Exception as e:
        # Handle any errors during AI generation or JSON parsing.
        # Log the error for debugging and return an error response dictionary.
        logging.error(f"Error in get_gemini_profile: {e}")
        return {"error": "Failed to generate Gemini profile."}

# --- Gemini AI Integration: Doppelganger ZIP Code Matching ---
def find_doppelgangers(data):
    """
    Finds other US ZIP codes with similar demographic profiles using Google's Gemini AI.
    
    This function uses Google's Generative AI to analyze demographic data for a given
    ZIP code and identify other ZIP codes across the United States that have remarkably
    similar demographic characteristics. The AI compares multiple demographic metrics
    including income, home values, population size, education levels, housing tenure,
    and age distribution to find "doppelganger" communities.
    
    This is a Python port of the TypeScript 'findDoppelgangers' function from
    doppelgangerService.ts to maintain consistency across the application stack.
    
    Args:
        data (dict): A dictionary containing demographic data for a ZIP code.
            Expected keys include: zipCode, medianIncome, medianHomeValue, population,
            medianAge, ownerOccupied, housingUnits, educationBachelors, educationGraduate,
            educationPopulation.
    
    Returns:
        list: A list of dictionaries, each containing:
            - zipCode (str): The 5-digit ZIP code
            - city (str): The primary city for the ZIP code
            - state (str): The 2-letter state abbreviation
            - similarityReason (str): Brief explanation of why this ZIP is a good match
            - similarityPercentage (float): Numerical similarity score (85-100)
            - OR {"error": str} if the AI generation fails
    
    Raises:
        Exception: If the Gemini API call fails or response cannot be parsed.
        
    Example:
        >>> demographics = fetch_census_demographics("90210")
        >>> doppelgangers = find_doppelgangers(demographics)
        >>> len(doppelgangers)
        5
    """
    logging.info(f"Finding doppelgangers for ZIP: {data['zipCode']}")

    # --- Configuration Parameters ---
    # These parameters control the doppelganger search behavior.
    # They are hardcoded to match the TypeScript implementation.
    
    # Number of similar ZIP codes to return.
    # The AI will find and rank the top N most similar ZIP codes.
    count = 5
    
    # Similarity score thresholds: Minimum and maximum values for the similarity percentage.
    # The AI will only return ZIP codes with similarity scores in this range.
    # A score of 100 represents a perfect match, while 85 is the minimum acceptable match.
    threshold_min = 85
    threshold_max = 100

    # --- Calculate Derived Metrics for Prompt ---
    # Convert raw demographic data to percentages for comparison.
    # These percentages are used in the AI prompt to describe the target demographic profile.
    
    # Higher education percentage: Proportion of adults with Bachelor's or higher.
    # This is used as a key matching criterion for finding similar communities.
    higher_ed_percent = (
        (data['educationBachelors'] + data['educationGraduate']) / 
        data['educationPopulation'] * 100 
        if data['educationPopulation'] > 0 else 0
    )
    
    # Owner-occupied housing percentage: Proportion of housing units that are owner-occupied.
    # This indicates the stability and investment characteristics of the community.
    owner_occupied_percent = (
        data['ownerOccupied'] / data['housingUnits'] * 100 
        if data['housingUnits'] > 0 else 0
    )

    # --- Construct AI Prompt ---
    # Build a detailed prompt that instructs the AI to act as a backend data service
    # and find similar ZIP codes based on demographic similarity.
    # 
    # The prompt includes:
    # - Clear instructions about the task (finding doppelganger ZIP codes)
    # - Key demographic metrics to prioritize in matching
    # - Similarity score requirements
    # - Output format requirements (JSON schema)
    # 
    # This prompt is ported directly from the TypeScript doppelgangerService.ts.
    prompt = f"""
        Analyze the provided demographic data for ZIP code {data['zipCode']} and act as a backend data service.
        Your task is to find {count} other US ZIP codes that are its "doppelgänger" – meaning they are remarkably similar across key metrics.
        
        Prioritize areas with a similar blend of:
        1.  Median Household Income (around {format_currency(data['medianIncome'])})
        2.  Median Home Value (around {format_currency(data['medianHomeValue'])})
        3.  Population size (around {format_number(data['population'])})
        4.  Education level (approx. {format_percent(higher_ed_percent)} with Bachelor's degree or higher)
        5.  Housing tenure (approx. {format_percent(owner_occupied_percent)} owner-occupied)
        6.  Median Age (around {data['medianAge']:.1f} years)

        For each match, you must provide a 'similarityPercentage' score between {threshold_min} and {threshold_max}, where 100 is a perfect match.
        Return the results as a JSON array of objects that strictly follows the provided schema. Do not include the original ZIP code ({data['zipCode']}) in the results.
    """
    
    # --- Define JSON Schema for AI Response ---
    # Specify the expected structure of the AI-generated response using JSON Schema.
    # This ensures the AI returns an array of doppelganger ZIP codes with consistent formatting.
    # The schema is a Python translation of the TypeScript responseSchema.
    schema = {
        "type": "array",
        "description": f"A list of {count} US ZIP codes with very similar demographics.",
        "items": {
            "type": "object",
            "properties": {
                "zipCode": {"type": "string", "description": "The 5-digit ZIP code."},
                "city": {"type": "string", "description": "The primary city for the ZIP code."},
                "state": {"type": "string", "description": "The 2-letter state abbreviation."},
                "similarityReason": {"type": "string", "description": "A brief, one-sentence explanation of why this ZIP code is a good match."},
                "similarityPercentage": {"type": "number", "description": f"A numerical score from {threshold_min} to {threshold_max}."}
            },
            "required": ["zipCode", "city", "state", "similarityReason", "similarityPercentage"]
        }
    }

    try:
        # Initialize the Gemini Generative Model.
        # We use 'gemini-2.5-flash' which is fast and efficient for structured data generation.
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # Generate content using the Gemini AI model.
        # The generation_config specifies:
        # - response_mime_type: Forces the response to be JSON format
        # - response_schema: Validates the response structure matches our schema
        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": schema
            }
        )
        
        # Parse the JSON response from the AI model.
        # The response.text contains a JSON array of doppelganger ZIP codes.
        return json.loads(response.text)
    except Exception as e:
        # Handle any errors during AI generation or JSON parsing.
        # Log the error for debugging and return an error response dictionary.
        logging.error(f"Error in find_doppelgangers: {e}")
        return {"error": "Failed to find doppelgangers."}

# --- Flask Application: Main API Endpoint ---
# Initialize the Flask application instance.
# Flask is a lightweight web framework that allows us to create REST API endpoints.
app = Flask(__name__)

# --- Enable CORS for your entire app ---
# This tells Flask to automatically handle OPTIONS requests
# and add the "Access-Control-Allow-Origin: *" header to all responses.
# This is essential for cross-origin requests from web browsers.
CORS(app)

@app.route('/find-twin', methods=['POST', 'OPTIONS'])
def handle_find_twin():
    """
    Main API endpoint for finding demographic doppelgangers for a given ZIP code.
    
    This endpoint orchestrates the entire workflow:
    1. Receives a ZIP code from the client (Node.js API)
    2. *** NEW: Checks Firestore for a cached response for this ZIP code. ***
    3. If cache miss:
       a. Fetches demographic data from the US Census Bureau API
       b. Generates a community profile using Google's Gemini AI
       c. Finds similar ZIP codes (doppelgangers) using Google's Gemini AI
       d. *** NEW: Saves the combined result to the Firestore cache. ***
    4. Returns all results as a JSON response (from cache or new)
    
    The endpoint expects a POST request with a JSON body containing:
    {
        "zip_code": "90210"  # A 5-digit US ZIP code
    }
    
    Returns:
        JSON response with HTTP status code:
        - 200 OK: Successfully processed request with demographics, profile, and doppelgangers
        - 400 Bad Request: Missing or invalid zip_code in request body
        - 404 Not Found: No demographic data found for the given ZIP code
        - 500 Internal Server Error: Unexpected error during processing
    
    Response format (200 OK):
    {
        "demographics": {
            # Raw demographic data from Census API
            "name": "...",
            "population": 12345,
            "medianIncome": 123456,
            # ... other demographic fields
        },
        "profile": {
            # AI-generated community profile
            "whoAreWe": "...",
            "ourNeighborhood": [...],
            "socioeconomicTraits": [...]
        },
        "doppelgangers": [
            # Array of similar ZIP codes
            {
                "zipCode": "12345",
                "city": "...",
                "state": "...",
                "similarityReason": "...",
                "similarityPercentage": 95.5
            },
            # ... more doppelgangers
        ]
    }
    
    Example:
        POST /find-twin
        Body: {"zip_code": "90210"}
        
        Response: {
            "demographics": {...},
            "profile": {...},
            "doppelgangers": [...]
        }
    """
    # Handle OPTIONS requests (CORS preflight) - Flask-CORS handles this automatically,
    # but we need to check here to avoid trying to parse JSON from an OPTIONS request
    if request.method == 'OPTIONS':
        # Flask-CORS will automatically add the necessary CORS headers
        # Return an empty response with 200 status
        return '', 200
    
    try:
        # --- Step 1: Validate and Extract Request Data ---
        # Parse the JSON request body sent by the client.
        # The client should send a JSON object with a 'zip_code' field.
        data = request.get_json()
        
        # Validate that the request contains valid JSON and includes the required field.
        # If validation fails, return a 400 Bad Request error with a descriptive message.
        if not data or 'zip_code' not in data:
            return jsonify({"error": "Missing 'zip_code' in JSON body"}), 400
        
        # Extract the ZIP code from the request data.
        # Convert to string to ensure consistent formatting (e.g., handle numeric ZIP codes).
        zip_code = str(data['zip_code']) # --- CHANGED: Ensure zip_code is a string for cache key
        logging.info(f"Received request for ZIP code: {zip_code}")

        # --- NEW: CACHE LOGIC (Step 1: Check Cache) ---
        # We will only attempt to use the cache if the 'db' client
        # was successfully initialized at startup.
        if db:
            # Define the document reference in Firestore.
            # We use a collection named 'zip_cache' and set the
            # document ID to be the zip_code itself for easy lookup.
            cache_ref = db.collection('zip_cache').document(zip_code)
            
            # Attempt to retrieve the document from Firestore.
            cached_data = cache_ref.get()
            
            # Check if the document exists in the cache.
            if cached_data.exists:
                # CACHE HIT! The data was found.
                logging.warning(f"CACHE HIT for ZIP: {zip_code}")
                # Return the data directly from the cache.
                # .to_dict() converts the Firestore document to a Python dictionary.
                return jsonify(cached_data.to_dict()), 200
            
            # CACHE MISS! The data was not found.
            logging.warning(f"CACHE MISS for ZIP: {zip_code}. Fetching new data.")
        
        # --- Step 2: Fetch Demographic Data from Census API ---
        # (This section only runs on a Cache Miss)
        # Query the US Census Bureau API to retrieve comprehensive demographic data
        # for the specified ZIP code. This includes population, income, housing,
        # education, age distribution, and other demographic metrics.
        demographics = fetch_census_demographics(zip_code)
        
        # If no demographic data was found (e.g., invalid ZIP code or API error),
        # return a 404 Not Found error with a descriptive message.
        if not demographics:
            return jsonify({"error": f"No demographic data found for ZIP code {zip_code}."}), 404

        # --- Step 3: Generate AI Insights Using Gemini ---
        # (This section only runs on a Cache Miss)
        # Use Google's Gemini AI to analyze the demographic data and generate insights.
        # We make two separate AI calls:
        # 1. Generate a narrative community profile
        # 2. Find similar ZIP codes (doppelgangers)
        # 
        # Note: These calls are made sequentially for simplicity. In a production
        # environment, these could potentially be parallelized for better performance.
        
        # Call 1: Generate Community Profile
        # Use Gemini AI to create a narrative description of the community, including
        # insights about the population, neighborhood characteristics, and socioeconomic traits.
        profile = get_gemini_profile(demographics)
        
        # Call 2: Find Doppelganger ZIP Codes
        # Use Gemini AI to identify other US ZIP codes with similar demographic profiles.
        # The AI compares multiple demographic metrics to find remarkably similar communities.
        doppelgangers = find_doppelgangers(demographics)
        
        # --- NEW: Combine results into a variable ---
        # We store the final payload in a variable so we can
        # both cache it AND return it.
        final_result = {
            "demographics": demographics,
            "profile": profile,
            "doppelgangers": doppelgangers
        }

        # --- NEW: CACHE LOGIC (Step 2: Save to Cache) ---
        # If the Firestore client is working, save this new result.
        if db:
            try:
                # Use .set() to create (or overwrite) the document
                # at our 'zip_cache/ZIP_CODE' reference.
                cache_ref.set(final_result)
                logging.info(f"Successfully cached new data for ZIP: {zip_code}")
            except Exception as e:
                # If caching fails, just log the error.
                # We should still return the data to the user.
                # Failing to cache should not fail the user's request.
                logging.error(f"Failed to cache data for ZIP {zip_code}: {e}")

        # --- Step 4: Format and Return Response ---
        # (This section now returns the 'final_result' variable)
        # Return a 200 OK status with the combined results.
        return jsonify(final_result), 200

    except Exception as e:
        # --- Error Handling ---
        # Catch any unexpected errors that occur during request processing.
        # This includes errors from:
        # - Request parsing (shouldn't happen due to validation above)
        # - Census API calls (handled in fetch_census_demographics, but catch here too)
        # - Gemini AI calls (handled in individual functions, but catch here too)
        # - JSON serialization errors
        # 
        # Log the error for debugging purposes and return a generic 500 error
        # to avoid exposing internal implementation details to the client.
        logging.error(f"An error occurred in /find-twin: {e}")
        return jsonify({"error": "An internal server error occurred."}), 500

# --- Application Entry Point ---
# This block runs when the script is executed directly (not when imported as a module).
# It starts the Flask development server to handle incoming HTTP requests.
if __name__ == "__main__":
    # Get the port number from environment variable PORT, defaulting to 8080 if not set.
    # This allows the application to be configured for different deployment environments
    # (e.g., Heroku sets PORT automatically, local development uses 8080).
    port = int(os.environ.get('PORT', 8080))
    
    # Start the Flask development server.
    # - debug=True: Enables debug mode with auto-reload on code changes and detailed error pages
    #   (Note: Should be False in production for security)
    # - host='0.0.0.0': Binds to all network interfaces, allowing external connections
    #   (Required for Docker containers and cloud deployments)
    # - port=port: Uses the port number determined above
    app.run(debug=True, host='0.0.0.0', port=port)
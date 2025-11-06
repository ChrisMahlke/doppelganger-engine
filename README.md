# Doppelganger Engine

<p align="center">
  <img src="https://img.shields.io/badge/Google_Cloud_Run-4285F4?style=for-the-badge&logo=googlecloud&logoColor=white" alt="Google Cloud Run">
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white" alt="Flask">
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge" alt="License: MIT">
</p>

A Python Flask backend service that finds demographic "doppelgangers" for US ZIP codes. This service fetches census data from the US Census Bureau API, analyzes it using Google's Gemini AI, and identifies similar ZIP codes with matching demographic profiles.

> **Part of the Demographic Doppelgänger Project**  
> 🌐 [Live Application](https://demographic-doppelganger-71027948544.us-west1.run.app/) | [Frontend Repository](https://github.com/ChrisMahlke/doppelganger) | [API Gateway Spec](https://github.com/ChrisMahlke/api-gateway-spec)

## Architecture

This service is part of a multi-tier architecture:

```
Frontend (React) 
    ↓
Google API Gateway (Public Entry Point)
    ↓ (IAM Authentication)
This Service (Private Python Engine)
    ↓
Firestore (Cache) + Census API + Gemini AI
```

### Service Role

The `doppelganger-engine` serves as the **private compute engine** in the architecture:

- **Public Access**: None - service requires IAM authentication
- **Authentication**: Only accessible via Google API Gateway using IAM service account
- **Purpose**: Handles all heavy computation including Census data fetching, AI analysis, and caching

### Workflow

The service follows a multi-step workflow:

1. **Cache Check**: First checks Firestore for a cached response for the requested ZIP code
2. **Data Fetching**: If cache miss, fetches demographic data from the US Census Bureau API
3. **AI Analysis**: Generates two types of insights using Gemini AI:
   - **Community Profile**: Narrative description of the area's character, lifestyle, and socioeconomic traits
   - **Doppelganger Matching**: Identifies similar ZIP codes based on demographic similarity
4. **Caching**: Stores the combined result in Firestore for future requests
5. **Response**: Returns demographics, profile, and doppelgangers as JSON

## Features

- **Census Data Integration**: Fetches comprehensive demographic data from the US Census Bureau's American Community Survey (ACS) 5-Year Estimates API
- **AI-Powered Analysis**: Uses Google's Gemini AI to generate detailed community profiles and find similar ZIP codes
- **Firestore Caching**: Implements intelligent caching using Google Cloud Firestore to reduce API calls and improve response times
- **CORS Support**: Handles CORS preflight requests (OPTIONS) for cross-origin browser access
- **RESTful API**: Provides a simple POST endpoint for finding demographic twins

## Environment Variables

The following environment variables must be set:

- `GEMINI_API_KEY`: Your Google Gemini API key for AI operations
- `PORT`: (Optional) Port number for the Flask server (defaults to 8080)
- `GOOGLE_APPLICATION_CREDENTIALS`: (Optional) Path to service account JSON for Firestore. If running on Google Cloud Run, Firestore will use the service account automatically.

## Dependencies

See `requirements.txt` for the complete list:

- `Flask`: Web framework for the REST API
- `gunicorn`: WSGI HTTP server for production
- `google-generativeai`: Google's Gemini AI SDK
- `requests`: HTTP library for Census API calls
- `google-cloud-firestore`: Google Cloud Firestore client for caching
- `flask-cors`: CORS support for cross-origin requests

## Installation

1. Clone the repository
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## Local Development

1. Create a `.env` file in the root directory (or set environment variables):

   ```bash
   # Create .env file
   cat > .env << EOF
   # Google Gemini API Key
   GEMINI_API_KEY=your-gemini-api-key-here
   
   # Server Port (Optional)
   PORT=8080
   EOF
   ```

   Or set environment variables directly:

   ```bash
   export GEMINI_API_KEY="your-api-key-here"
   export PORT=8080  # Optional
   ```

2. Run the Flask development server:

   ```bash
   python main.py
   ```

The server will start on `http://localhost:8080` (or the PORT specified).

## API Endpoint

### POST `/find-twin`

Finds demographic doppelgangers for a given ZIP code.

**Request Body:**

```json
{
  "zip_code": "90210"
}
```

**Response (200 OK):**

```json
{
  "demographics": {
    "name": "ZIP Code Tabulation Area 90210",
    "population": 20575,
    "medianIncome": 123456,
    "medianAge": 42.5,
    ...
  },
  "profile": {
    "whoAreWe": "A narrative description of the community...",
    "ourNeighborhood": ["Fact 1", "Fact 2", ...],
    "socioeconomicTraits": ["Trait 1", "Trait 2", ...]
  },
  "doppelgangers": [
    {
      "zipCode": "12345",
      "city": "City Name",
      "state": "CA",
      "similarityReason": "Similar income and education levels",
      "similarityPercentage": 95.5
    },
    ...
  ]
}
```

**Error Responses:**

- `400 Bad Request`: Missing or invalid `zip_code` in request body
- `404 Not Found`: No demographic data found for the given ZIP code
- `500 Internal Server Error`: Unexpected error during processing

### OPTIONS `/find-twin`

Handles CORS preflight requests. Returns 200 OK with appropriate CORS headers.

## Caching

The service implements intelligent caching using Google Cloud Firestore:

- **Cache Key**: The ZIP code is used as the document ID in the `zip_cache` collection
- **Cache Hit**: If cached data exists, it's returned immediately without API calls (< 1 second response time)
- **Cache Miss**: New data is fetched, processed, and then cached for future requests
- **Graceful Degradation**: If Firestore is unavailable, the service continues to function without caching

The Firestore client is initialized at startup. If initialization fails (e.g., missing permissions), the service will log a warning but continue operating without caching.

## Deployment

### Docker

Build the Docker image:

```bash
docker build -t doppelganger-engine .
```

Run the container:

```bash
docker run -p 8080:8080 -e GEMINI_API_KEY="your-api-key" doppelganger-engine
```

### Google Cloud Run

1. Build and push the container:

   ```bash
   gcloud builds submit --tag gcr.io/PROJECT_ID/doppelganger-engine
   ```

2. Deploy to Cloud Run:

   ```bash
   gcloud run deploy doppelganger-engine \
     --image gcr.io/PROJECT_ID/doppelganger-engine \
     --platform managed \
     --region us-central1 \
     --set-env-vars GEMINI_API_KEY=your-api-key \
     --memory=2Gi \
     --timeout=120s \
     --min-instances=1 \
     --no-allow-unauthenticated
   ```

**Important Configuration:**

- `--memory=2Gi`: Required for handling large datasets and AI model libraries
- `--timeout=120s`: Allows time for Census API calls and Gemini AI processing
- `--min-instances=1`: Eliminates cold starts for better user experience
- `--no-allow-unauthenticated`: Requires IAM authentication - only the API Gateway can invoke this service

**IAM Permissions:**

The API Gateway service account needs permission to invoke this service:

```bash
# Get the API Gateway service account
GATEWAY_SA="doppelganger-gateway-sa@PROJECT_ID.iam.gserviceaccount.com"

# Grant permission
gcloud run services add-iam-policy-binding doppelganger-engine \
  --region=us-central1 \
  --member="serviceAccount:${GATEWAY_SA}" \
  --role="roles/run.invoker"
```

**Note**: For Firestore caching on Cloud Run, ensure the Cloud Run service has the "Cloud Datastore User" role or appropriate Firestore permissions.

## Project Structure

```
doppelganger-engine/
├── main.py              # Main Flask application
├── requirements.txt     # Python dependencies
├── Dockerfile           # Docker configuration
└── README.md            # This file
```

## Integration with API Gateway

This service is designed to work with **Google API Gateway**:

1. The service is deployed as a **private** Cloud Run service (requires IAM authentication)
2. Google API Gateway routes public requests to this service
3. The API Gateway service account has `roles/run.invoker` permission on this service
4. All requests come through the API Gateway, which handles authentication, CORS, and routing

**Request Flow:**
```
Public Request → API Gateway (validates API key) 
  → IAM Authentication → This Service → Response
```

## CORS Configuration

The service handles CORS requests:

- **OPTIONS requests**: Automatically handled by Flask-CORS, returns 200 OK
- **POST requests**: Requires valid request body with `zip_code`
- **CORS headers**: Automatically added to all responses

## Notes

- The service is designed to work with the Google API Gateway architecture
- Firestore caching is optional and will gracefully degrade if unavailable
- All Census API data is from the 2022 ACS 5-Year Estimates
- The service uses Gemini 2.5 Flash model for fast, efficient AI processing
- Service timeout (120s) matches API Gateway deadline configuration

## Related Repositories

This service is part of the **Demographic Doppelgänger** project:

- 🌐 **Live Application**: [https://demographic-doppelganger-71027948544.us-west1.run.app/](https://demographic-doppelganger-71027948544.us-west1.run.app/)
- 🎨 **Frontend Repository**: [doppelganger](https://github.com/ChrisMahlke/doppelganger) - React/TypeScript frontend
- 🚪 **API Gateway Specification**: [api-gateway-spec](https://github.com/ChrisMahlke/api-gateway-spec) - OpenAPI 2.0 spec for the gateway
- 🔧 **Node.js API** (Deprecated): [doppelganger-api](https://github.com/ChrisMahlke/doppelganger-api) - Legacy Node.js gateway service

## Performance Considerations

- **First Request (Cache Miss)**: 20-60 seconds (Census API + 2x Gemini AI calls)
- **Subsequent Requests (Cache Hit)**: < 1 second (served from Firestore)
- **Memory**: 2Gi RAM required for large data processing and AI libraries
- **Timeout**: 120 seconds allows for complete request processing

## Security

- **No Public Access**: Service requires IAM authentication
- **Service Account**: Only API Gateway service account can invoke
- **Secrets**: Gemini API key stored in environment variables (not in code)
- **Firestore**: Uses Cloud Run service account for authentication

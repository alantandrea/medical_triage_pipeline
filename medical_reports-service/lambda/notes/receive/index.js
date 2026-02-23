/**
 * Receive Patient Note Lambda
 *
 * Receives SMS messages from patients via Twilio webhook.
 * Uses AWS Bedrock (Claude Haiku) to extract structured medical data from unstructured text.
 *
 * Flow:
 * 1. Receive SMS from Twilio (POST /notes)
 * 2. Lookup patient by phone number
 * 3. Extract vitals/symptoms using Bedrock Haiku
 * 4. Store structured data in DynamoDB
 * 5. Return TwiML response to patient
 *
 * @endpoint POST /notes
 */

const { DynamoDBClient } = require('@aws-sdk/client-dynamodb');
const { DynamoDBDocumentClient, PutCommand, QueryCommand } = require('@aws-sdk/lib-dynamodb');
const { BedrockRuntimeClient, InvokeModelCommand } = require('@aws-sdk/client-bedrock-runtime');
const { v4: uuidv4 } = require('uuid');

const dynamoClient = new DynamoDBClient({});
const docClient = DynamoDBDocumentClient.from(dynamoClient);
const bedrockClient = new BedrockRuntimeClient({ region: 'us-east-1' });

/**
 * Extract structured medical data from patient message using Claude Haiku.
 * Handles variations like "a-one-c is five point two" -> hemoglobin_a1c: 5.2
 *
 * @param {string} messageText - Raw SMS text from patient
 * @returns {Object} Extracted and validated medical data
 */
async function extractMedicalData(messageText) {
  const prompt = `You are a medical data extraction AI. Extract health measurements and symptoms from this patient message.

IMPORTANT RULES:
1. Understand variations: "a-one-c", "a1c", "HbA1c" all mean hemoglobin_a1c
2. Convert number words: "five point two" = 5.2, "hundred one" = 101
3. "sugar" or "blood sugar" = blood_sugar_level (mg/dL)
4. "temp" or "temperature" or "fever" = temperature (Fahrenheit for US patients)
5. "oxygen", "O2", "sat", "pulse ox" = sp02 (percentage)
6. "pressure" or "BP" with two numbers = systolic/diastolic
7. Pain on scale of 1-10 = pain_scale
8. Extract any symptoms mentioned (dizziness, nausea, chest pain, etc.)
9. Note urgency indicators (chest pain, difficulty breathing, severe pain, etc.)
10. Return ONLY valid JSON, no explanation

PATIENT MESSAGE:
"${messageText}"

Extract to this JSON structure (use null for values not mentioned):
{
  "note_text": "${messageText}",
  "temperature": <number or null>,
  "pain_scale": <0-10 integer or null>,
  "sp02": <50-100 integer or null>,
  "systolic": <integer or null>,
  "diastolic": <integer or null>,
  "weight": <number or null>,
  "blood_sugar_level": <integer or null>,
  "heart_rate": <integer or null>,
  "hemoglobin_a1c": <number or null>,
  "symptoms": [<list of symptoms mentioned>],
  "urgency_indicators": [<any concerning symptoms requiring immediate attention>],
  "extraction_confidence": "high" | "medium" | "low"
}

JSON:`;

  try {
    const response = await bedrockClient.send(new InvokeModelCommand({
      modelId: 'anthropic.claude-3-haiku-20240307-v1:0',
      contentType: 'application/json',
      accept: 'application/json',
      body: JSON.stringify({
        anthropic_version: "bedrock-2023-05-31",
        max_tokens: 512,
        temperature: 0.1,  // Low temperature for consistent extraction
        messages: [{
          role: "user",
          content: prompt
        }]
      })
    }));

    const responseBody = JSON.parse(new TextDecoder().decode(response.body));
    const extractedText = responseBody.content[0].text;

    // Parse JSON from response
    const jsonMatch = extractedText.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      const parsed = JSON.parse(jsonMatch[0]);
      return validateExtractedData(parsed, messageText);
    }
  } catch (error) {
    console.error('Bedrock extraction failed:', error);
  }

  // Fallback: return just the text with no extracted values
  return {
    note_text: messageText,
    temperature: null,
    pain_scale: null,
    sp02: null,
    systolic: null,
    diastolic: null,
    weight: null,
    blood_sugar_level: null,
    heart_rate: null,
    hemoglobin_a1c: null,
    symptoms: [],
    urgency_indicators: [],
    extraction_confidence: 'low'
  };
}

/**
 * Validate extracted data with range checks (Pydantic-like validation).
 *
 * @param {Object} data - Raw extracted data from Bedrock
 * @param {string} originalText - Original message text
 * @returns {Object} Validated data with invalid values set to null
 */
function validateExtractedData(data, originalText) {
  const validated = {
    note_text: originalText,
    temperature: null,
    pain_scale: null,
    sp02: null,
    systolic: null,
    diastolic: null,
    weight: null,
    blood_sugar_level: null,
    heart_rate: null,
    hemoglobin_a1c: null,
    symptoms: [],
    urgency_indicators: [],
    extraction_confidence: data.extraction_confidence || 'medium'
  };

  // Temperature: 90-115 F (reasonable range)
  if (data.temperature && data.temperature >= 90 && data.temperature <= 115) {
    validated.temperature = Math.round(data.temperature * 10) / 10;
  }

  // Pain scale: 0-10
  if (data.pain_scale !== null && data.pain_scale >= 0 && data.pain_scale <= 10) {
    validated.pain_scale = Math.round(data.pain_scale);
  }

  // SpO2: 50-100%
  if (data.sp02 && data.sp02 >= 50 && data.sp02 <= 100) {
    validated.sp02 = Math.round(data.sp02);
  }

  // Systolic BP: 50-300 mmHg
  if (data.systolic && data.systolic >= 50 && data.systolic <= 300) {
    validated.systolic = Math.round(data.systolic);
  }

  // Diastolic BP: 30-200 mmHg
  if (data.diastolic && data.diastolic >= 30 && data.diastolic <= 200) {
    validated.diastolic = Math.round(data.diastolic);
  }

  // Weight: 1-1000 lbs
  if (data.weight && data.weight >= 1 && data.weight <= 1000) {
    validated.weight = Math.round(data.weight * 10) / 10;
  }

  // Blood sugar: 20-800 mg/dL
  if (data.blood_sugar_level && data.blood_sugar_level >= 20 && data.blood_sugar_level <= 800) {
    validated.blood_sugar_level = Math.round(data.blood_sugar_level);
  }

  // Heart rate: 20-300 bpm
  if (data.heart_rate && data.heart_rate >= 20 && data.heart_rate <= 300) {
    validated.heart_rate = Math.round(data.heart_rate);
  }

  // Hemoglobin A1c: 3-20%
  if (data.hemoglobin_a1c && data.hemoglobin_a1c >= 3 && data.hemoglobin_a1c <= 20) {
    validated.hemoglobin_a1c = Math.round(data.hemoglobin_a1c * 10) / 10;
  }

  // Symptoms: array of strings
  if (Array.isArray(data.symptoms)) {
    validated.symptoms = data.symptoms.filter(s => typeof s === 'string' && s.length > 0);
  }

  // Urgency indicators: array of strings
  if (Array.isArray(data.urgency_indicators)) {
    validated.urgency_indicators = data.urgency_indicators.filter(s => typeof s === 'string' && s.length > 0);
  }

  return validated;
}

/**
 * Lookup patient by phone number using GSI.
 *
 * @param {string} phoneNumber - Phone number from Twilio (e.g., "+15551234567")
 * @returns {Object|null} Patient record or null if not found
 */
async function lookupPatientByPhone(phoneNumber) {
  // Normalize phone number: remove all non-digits, take last 10 digits
  const normalized = phoneNumber.replace(/\D/g, '').slice(-10);

  // Try all common phone formats stored in DynamoDB
  const formats = [
    normalized,                                    // 5551234567
    `${normalized.slice(0,3)}-${normalized.slice(3,6)}-${normalized.slice(6)}`, // 555-123-4567
    `(${normalized.slice(0,3)}) ${normalized.slice(3,6)}-${normalized.slice(6)}`, // (555) 123-4567
  ];

  for (const format of formats) {
    try {
      const result = await docClient.send(new QueryCommand({
        TableName: process.env.PATIENT_MASTER_TABLE,
        IndexName: 'cell-phone-index',
        KeyConditionExpression: 'cell_phone = :phone',
        ExpressionAttributeValues: {
          ':phone': format
        },
        Limit: 1
      }));

      if (result.Items && result.Items.length > 0) {
        return result.Items[0];
      }
    } catch (error) {
      console.error(`Phone lookup failed for format ${format}:`, error);
    }
  }

  return null;
}

/**
 * Count how many values were successfully extracted.
 *
 * @param {Object} data - Extracted data object
 * @returns {number} Count of non-null extracted values
 */
function countExtractedValues(data) {
  const fields = [
    'temperature', 'pain_scale', 'sp02', 'systolic', 'diastolic',
    'weight', 'blood_sugar_level', 'heart_rate', 'hemoglobin_a1c'
  ];
  return fields.filter(f => data[f] !== null && data[f] !== undefined).length;
}

/**
 * Generate TwiML response for Twilio.
 *
 * @param {string} message - Message to send back to patient
 * @returns {Object} API Gateway response with TwiML body
 */
function twilioResponse(message) {
  const twiml = `<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Message>${message}</Message>
</Response>`;

  return {
    statusCode: 200,
    headers: {
      'Content-Type': 'text/xml'
    },
    body: twiml
  };
}

/**
 * Main Lambda handler.
 * Receives Twilio webhook, extracts data, stores note, returns confirmation.
 */
exports.handler = async (event) => {
  console.log('Received event:', JSON.stringify(event, null, 2));

  try {
    // Parse Twilio webhook body (application/x-www-form-urlencoded)
    let body = event.body;
    if (event.isBase64Encoded) {
      body = Buffer.from(body, 'base64').toString('utf-8');
    }

    const params = new URLSearchParams(body);
    const fromPhone = params.get('From');
    const messageBody = params.get('Body');

    // Validate required fields
    if (!fromPhone || !messageBody) {
      console.error('Missing required fields:', { fromPhone, messageBody });
      return twilioResponse('Invalid request. Please try again.');
    }

    console.log(`Received SMS from ${fromPhone}: ${messageBody}`);

    // 1. Lookup patient by phone number
    const patient = await lookupPatientByPhone(fromPhone);

    if (!patient) {
      console.log(`Unknown phone number: ${fromPhone}`);
      return twilioResponse(
        'Your phone number is not registered with our office. ' +
        'Please contact us to register your number for secure messaging.'
      );
    }

    console.log(`Found patient: ${patient.patient_id} - ${patient.first_name} ${patient.last_name}`);

    // 2. Extract structured data using Bedrock Haiku
    const extractedData = await extractMedicalData(messageBody);
    console.log('Extracted data:', JSON.stringify(extractedData, null, 2));

    // 3. Store in DynamoDB
    const noteId = uuidv4();
    const now = new Date().toISOString();

    const noteRecord = {
      // Keys
      patient_id: patient.patient_id,
      note_id: noteId,

      // Timestamps
      note_date: now,
      created_at: now,

      // Source info
      from_phone: fromPhone,
      patient_name: `${patient.first_name} ${patient.last_name}`,

      // Processing status (for /notes/pending query)
      processed: 'false',

      // Original text
      note_text: extractedData.note_text,

      // Extracted vitals (structured)
      temperature: extractedData.temperature,
      pain_scale: extractedData.pain_scale,
      sp02: extractedData.sp02,
      systolic: extractedData.systolic,
      diastolic: extractedData.diastolic,
      weight: extractedData.weight,
      blood_sugar_level: extractedData.blood_sugar_level,
      heart_rate: extractedData.heart_rate,
      hemoglobin_a1c: extractedData.hemoglobin_a1c,

      // Extracted symptoms and urgency
      symptoms: extractedData.symptoms,
      urgency_indicators: extractedData.urgency_indicators,

      // Metadata
      extraction_method: 'bedrock-haiku',
      extraction_confidence: extractedData.extraction_confidence,
      values_extracted: countExtractedValues(extractedData),
      has_urgency: extractedData.urgency_indicators.length > 0
    };

    await docClient.send(new PutCommand({
      TableName: process.env.PATIENT_NOTES_TABLE,
      Item: noteRecord
    }));

    console.log(`Stored note ${noteId} for patient ${patient.patient_id}`);

    // 4. Return SMS confirmation
    return twilioResponse(
      'We have received your submission and will analyze it. ' +
      'If you are experiencing a medical emergency, call 911 immediately without delay!'
    );

  } catch (error) {
    console.error('Error processing patient note:', error);
    return twilioResponse(
      'We encountered an error processing your message. ' +
      'Please try again or call our office directly.'
    );
  }
};

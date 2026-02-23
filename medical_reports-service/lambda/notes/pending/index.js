/**
 * Get Pending Patient Notes Lambda
 *
 * Returns patient notes that have not yet been processed by the AI system.
 * Used by the DGX Spark edge code to poll for new patient-submitted notes.
 *
 * @endpoint GET /notes/pending
 * @query {number} limit - Maximum number of notes to return (default: 50)
 *
 * @returns {Object} Response with pending_notes array
 */

const { DynamoDBClient } = require('@aws-sdk/client-dynamodb');
const { DynamoDBDocumentClient, QueryCommand } = require('@aws-sdk/lib-dynamodb');

const dynamoClient = new DynamoDBClient({});
const docClient = DynamoDBDocumentClient.from(dynamoClient);

exports.handler = async (event) => {
  console.log('Get pending notes request:', JSON.stringify(event, null, 2));

  try {
    // Parse query parameters
    const limit = parseInt(event.queryStringParameters?.limit) || 50;

    // Query unprocessed notes using GSI
    // Note: 'processed' is a DynamoDB reserved keyword, so we use ExpressionAttributeNames
    const result = await docClient.send(new QueryCommand({
      TableName: process.env.PATIENT_NOTES_TABLE,
      IndexName: 'processed-index',
      KeyConditionExpression: '#p = :p',
      ExpressionAttributeNames: {
        '#p': 'processed'
      },
      ExpressionAttributeValues: {
        ':p': 'false'
      },
      Limit: limit,
      ScanIndexForward: true  // Oldest first (FIFO)
    }));

    const notes = result.Items || [];

    // Format response to match reports/pending structure
    const formattedNotes = notes.map(note => ({
      // Identifiers
      patient_id: note.patient_id,
      note_id: note.note_id,
      patient_name: note.patient_name,

      // Timestamps
      note_date: note.note_date,
      created_at: note.created_at,

      // Original content
      note_text: note.note_text,

      // Extracted vitals (pre-normalized by Bedrock)
      temperature: note.temperature,
      pain_scale: note.pain_scale,
      sp02: note.sp02,
      systolic: note.systolic,
      diastolic: note.diastolic,
      weight: note.weight,
      blood_sugar_level: note.blood_sugar_level,
      heart_rate: note.heart_rate,
      hemoglobin_a1c: note.hemoglobin_a1c,

      // Symptoms and urgency
      symptoms: note.symptoms || [],
      urgency_indicators: note.urgency_indicators || [],
      has_urgency: note.has_urgency || false,

      // Metadata
      extraction_confidence: note.extraction_confidence,
      values_extracted: note.values_extracted,
      processed: note.processed,

      // Type indicator for AI routing
      report_type: 'patient_note'
    }));

    console.log(`Returning ${formattedNotes.length} pending notes`);

    return {
      statusCode: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({
        pending_notes: formattedNotes,
        count: formattedNotes.length
      })
    };

  } catch (error) {
    console.error('Error fetching pending notes:', error);
    return {
      statusCode: 500,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({
        error: 'Failed to fetch pending notes',
        message: error.message
      })
    };
  }
};

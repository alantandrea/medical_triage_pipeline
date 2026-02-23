/**
 * Update Patient Note Lambda
 *
 * Marks a patient note as processed after the AI has analyzed it.
 * Can also update AI analysis results.
 *
 * @endpoint PATCH /notes/update/{note_id}
 * @param {string} note_id - Note identifier (path parameter)
 * @body {Object} Optional body with AI analysis results
 *
 * @returns {Object} Success/failure response
 */

const { DynamoDBClient } = require('@aws-sdk/client-dynamodb');
const { DynamoDBDocumentClient, UpdateCommand, QueryCommand } = require('@aws-sdk/lib-dynamodb');

const dynamoClient = new DynamoDBClient({});
const docClient = DynamoDBDocumentClient.from(dynamoClient);

exports.handler = async (event) => {
  console.log('Update note request:', JSON.stringify(event, null, 2));

  try {
    const noteId = event.pathParameters?.note_id;

    if (!noteId) {
      return {
        statusCode: 400,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({
          error: 'Missing note_id parameter'
        })
      };
    }

    // Parse optional body with AI results
    let aiResults = {};
    if (event.body) {
      try {
        aiResults = JSON.parse(event.body);
      } catch (e) {
        console.warn('Could not parse request body:', e);
      }
    }

    // Look up the note using the note_id GSI to get the patient_id (needed for update).
    // This is O(1) vs the old full-table Scan which failed past 1MB of data.
    const queryResult = await docClient.send(new QueryCommand({
      TableName: process.env.PATIENT_NOTES_TABLE,
      IndexName: 'note_id-index',
      KeyConditionExpression: 'note_id = :nid',
      ExpressionAttributeValues: {
        ':nid': noteId
      },
      Limit: 1
    }));

    if (!queryResult.Items || queryResult.Items.length === 0) {
      return {
        statusCode: 404,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({
          error: 'Note not found',
          note_id: noteId
        })
      };
    }

    const note = queryResult.Items[0];
    const processedAt = new Date().toISOString();

    // Build update expression
    // Note: 'processed' is a DynamoDB reserved keyword, so we use ExpressionAttributeNames
    let updateExpression = 'SET #p = :processed, processed_at = :processedAt';
    const expressionAttributeNames = {
      '#p': 'processed'
    };
    const expressionAttributeValues = {
      ':processed': 'true',
      ':processedAt': processedAt
    };

    // Add AI results if provided
    if (aiResults.ai_priority_score !== undefined) {
      updateExpression += ', ai_priority_score = :score';
      expressionAttributeValues[':score'] = aiResults.ai_priority_score;
    }
    if (aiResults.ai_interpretation) {
      updateExpression += ', ai_interpretation = :interp';
      expressionAttributeValues[':interp'] = aiResults.ai_interpretation;
    }
    if (aiResults.alert_level) {
      updateExpression += ', alert_level = :alert';
      expressionAttributeValues[':alert'] = aiResults.alert_level;
    }
    if (aiResults.alert_sent !== undefined) {
      updateExpression += ', alert_sent = :alertSent';
      expressionAttributeValues[':alertSent'] = aiResults.alert_sent;
    }

    // Update the note
    await docClient.send(new UpdateCommand({
      TableName: process.env.PATIENT_NOTES_TABLE,
      Key: {
        patient_id: note.patient_id,
        note_id: noteId
      },
      UpdateExpression: updateExpression,
      ExpressionAttributeNames: expressionAttributeNames,
      ExpressionAttributeValues: expressionAttributeValues
    }));

    console.log(`Marked note ${noteId} as processed`);

    return {
      statusCode: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({
        message: 'Note marked as processed',
        note_id: noteId,
        patient_id: note.patient_id,
        processed_at: processedAt
      })
    };

  } catch (error) {
    console.error('Error updating note:', error);
    return {
      statusCode: 500,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({
        error: 'Failed to update note',
        message: error.message
      })
    };
  }
};

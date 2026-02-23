const { DynamoDBClient } = require('@aws-sdk/client-dynamodb');
const { DynamoDBDocumentClient, UpdateCommand, QueryCommand } = require('@aws-sdk/lib-dynamodb');

const client = new DynamoDBClient({});
const docClient = DynamoDBDocumentClient.from(client);

exports.handler = async (event) => {
  try {
    const tableName = process.env.PATIENT_RESULTS_TABLE;
    const reportId = event.pathParameters.report_id;

    if (!reportId) {
      return {
        statusCode: 400,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({ error: 'Report ID is required' })
      };
    }

    // Parse request body for update fields
    let body = {};
    if (event.body) {
      body = JSON.parse(event.body);
    }

    // Look up the report using the report_id GSI to get the patient_id (needed for composite key).
    // This is O(1) vs the old full-table Scan which failed past 1MB of data.
    const queryResult = await docClient.send(new QueryCommand({
      TableName: tableName,
      IndexName: 'report_id-index',
      KeyConditionExpression: 'report_id = :rid',
      ExpressionAttributeValues: {
        ':rid': reportId
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
        body: JSON.stringify({ error: 'Report not found' })
      };
    }

    const existingReport = queryResult.Items[0];
    const processedAt = new Date().toISOString();

    // Build update expression
    let updateExpression = 'SET report_final_ind = :final, processed_at = :processedAt';
    const expressionAttributeValues = {
      ':final': 'true',
      ':processedAt': processedAt
    };

    // Store AI results if provided
    if (body.ai_summary) {
      updateExpression += ', ai_summary = :summary';
      expressionAttributeValues[':summary'] = body.ai_summary;
    }
    if (body.ai_severity) {
      updateExpression += ', ai_severity = :aiSev';
      expressionAttributeValues[':aiSev'] = body.ai_severity;
    }
    if (body.ai_urgency_score !== undefined) {
      updateExpression += ', ai_urgency_score = :urgScore';
      expressionAttributeValues[':urgScore'] = body.ai_urgency_score;
    }
    if (body.ai_priority_level) {
      updateExpression += ', ai_priority_level = :priLevel';
      expressionAttributeValues[':priLevel'] = body.ai_priority_level;
    }

    const updateResult = await docClient.send(new UpdateCommand({
      TableName: tableName,
      Key: {
        patient_id: existingReport.patient_id,
        report_id: reportId
      },
      UpdateExpression: updateExpression,
      ExpressionAttributeValues: expressionAttributeValues,
      ReturnValues: 'ALL_NEW'
    }));

    return {
      statusCode: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({
        message: 'Report marked as processed',
        report: updateResult.Attributes
      })
    };
  } catch (error) {
    console.error('Error updating report:', error);
    return {
      statusCode: 500,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({ error: error.message })
    };
  }
};

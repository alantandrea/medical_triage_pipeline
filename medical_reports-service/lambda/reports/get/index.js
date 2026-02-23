const { DynamoDBClient } = require('@aws-sdk/client-dynamodb');
const { DynamoDBDocumentClient, QueryCommand } = require('@aws-sdk/lib-dynamodb');
const { S3Client, GetObjectCommand } = require('@aws-sdk/client-s3');
const { getSignedUrl } = require('@aws-sdk/s3-request-presigner');

const dynamoClient = new DynamoDBClient({});
const docClient = DynamoDBDocumentClient.from(dynamoClient);
const s3Client = new S3Client({});

exports.handler = async (event) => {
  try {
    const tableName = process.env.PATIENT_RESULTS_TABLE;
    const bucketName = process.env.REPORTS_BUCKET;
    const patientId = parseInt(event.pathParameters.patient_id);

    if (isNaN(patientId)) {
      return {
        statusCode: 400,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        },
        body: JSON.stringify({ error: 'Invalid patient ID. Must be a number.' })
      };
    }

    // Query reports for this patient
    const result = await docClient.send(new QueryCommand({
      TableName: tableName,
      KeyConditionExpression: 'patient_id = :pid',
      ExpressionAttributeValues: {
        ':pid': patientId
      },
      ScanIndexForward: false // Most recent first
    }));

    // Generate pre-signed URLs for reports
    const reportsWithUrls = await Promise.all(result.Items.map(async (report) => {
      const enhancedReport = { ...report };

      if (report.report_pdf_s3_key) {
        enhancedReport.report_pdf_url = await getSignedUrl(
          s3Client,
          new GetObjectCommand({
            Bucket: bucketName,
            Key: report.report_pdf_s3_key
          }),
          { expiresIn: 3600 } // 1 hour
        );
      }

      if (report.report_image_s3_key) {
        enhancedReport.report_image_url = await getSignedUrl(
          s3Client,
          new GetObjectCommand({
            Bucket: bucketName,
            Key: report.report_image_s3_key
          }),
          { expiresIn: 3600 }
        );
      }

      return enhancedReport;
    }));

    return {
      statusCode: 200,
      headers: {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      },
      body: JSON.stringify({
        patient_id: patientId,
        reports: reportsWithUrls,
        count: reportsWithUrls.length
      })
    };
  } catch (error) {
    console.error('Error getting reports:', error);
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

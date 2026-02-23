const { DynamoDBClient } = require('@aws-sdk/client-dynamodb');
const { DynamoDBDocumentClient, QueryCommand } = require('@aws-sdk/lib-dynamodb');
const { S3Client, GetObjectCommand } = require('@aws-sdk/client-s3');
const { getSignedUrl } = require('@aws-sdk/s3-request-presigner');
const { STSClient, AssumeRoleCommand } = require('@aws-sdk/client-sts');

const dynamoClient = new DynamoDBClient({});
const docClient = DynamoDBDocumentClient.from(dynamoClient);
const stsClient = new STSClient({});

// Role chaining (Lambda execution role -> presign role) is capped at 1 hour by AWS.
// Set URL TTL to 3600s and use fresh AssumeRole credentials to guarantee the full hour.
// Edge should request batches of <=15 reports (15 * 3min = 45min, well within 1hr).
const PRESIGN_TTL = 3600; // 1 hour (matches role chaining max)

/**
 * Get an S3 client with fresh, long-lived credentials for pre-signing URLs.
 *
 * Lambda execution role credentials can expire before the pre-signed URL's TTL,
 * causing 403 Forbidden on download. By assuming a dedicated role with an explicit
 * session duration, we guarantee the signing credentials outlive the URL's expiresIn.
 */
async function getPresignS3Client() {
  const roleArn = process.env.PRESIGN_ROLE_ARN;

  if (!roleArn) {
    console.warn('PRESIGN_ROLE_ARN not set, falling back to default credentials');
    return new S3Client({});
  }

  const response = await stsClient.send(new AssumeRoleCommand({
    RoleArn: roleArn,
    RoleSessionName: `presign-${Date.now()}`,
    DurationSeconds: 3600, // Max for role chaining
  }));

  return new S3Client({
    credentials: {
      accessKeyId: response.Credentials.AccessKeyId,
      secretAccessKey: response.Credentials.SecretAccessKey,
      sessionToken: response.Credentials.SessionToken,
    },
  });
}

exports.handler = async (event) => {
  try {
    const tableName = process.env.PATIENT_RESULTS_TABLE;
    const bucketName = process.env.REPORTS_BUCKET;

    // Get limit from query string (default 50)
    const limit = event.queryStringParameters?.limit
      ? parseInt(event.queryStringParameters.limit)
      : 50;

    // Query using GSI for reports where report_final_ind is false
    const result = await docClient.send(new QueryCommand({
      TableName: tableName,
      IndexName: 'report_final_ind-index',
      KeyConditionExpression: 'report_final_ind = :status',
      ExpressionAttributeValues: {
        ':status': 'false'
      },
      Limit: limit,
      ScanIndexForward: true // Oldest first (FIFO)
    }));

    // Get S3 client with guaranteed-fresh credentials for pre-signing
    const presignClient = await getPresignS3Client();

    // Generate pre-signed URLs for reports
    const reportsWithUrls = await Promise.all(result.Items.map(async (report) => {
      const enhancedReport = { ...report };

      if (report.report_pdf_s3_key) {
        enhancedReport.report_pdf_url = await getSignedUrl(
          presignClient,
          new GetObjectCommand({
            Bucket: bucketName,
            Key: report.report_pdf_s3_key
          }),
          { expiresIn: PRESIGN_TTL }
        );
      }

      if (report.report_image_s3_key) {
        enhancedReport.report_image_url = await getSignedUrl(
          presignClient,
          new GetObjectCommand({
            Bucket: bucketName,
            Key: report.report_image_s3_key
          }),
          { expiresIn: PRESIGN_TTL }
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
        pending_reports: reportsWithUrls,
        count: reportsWithUrls.length
      })
    };
  } catch (error) {
    console.error('Error getting pending reports:', error);
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

import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { NodejsFunction } from 'aws-cdk-lib/aws-lambda-nodejs';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as path from 'path';

export class MedicalReportsServiceStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const prefix = 'medgemma-challenge';

    // ==================== S3 Buckets ====================

    // Bucket for generated reports (PDFs)
    const reportsBucket = new s3.Bucket(this, 'ReportsBucket', {
      bucketName: `${prefix}-reports-${this.account}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      cors: [
        {
          allowedMethods: [s3.HttpMethods.GET, s3.HttpMethods.PUT],
          allowedOrigins: ['*'],
          allowedHeaders: ['*'],
        },
      ],
    });

    // Bucket for real medical images from public datasets (NIH, LIDC, etc.)
    const medicalImagesBucket = new s3.Bucket(this, 'MedicalImagesBucket', {
      bucketName: `${prefix}-medical-images-${this.account}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      cors: [
        {
          allowedMethods: [s3.HttpMethods.GET, s3.HttpMethods.PUT],
          allowedOrigins: ['*'],
          allowedHeaders: ['*'],
        },
      ],
    });

    // ==================== DynamoDB Tables ====================

    // Patient Master Table
    const patientMasterTable = new dynamodb.Table(this, 'PatientMasterTable', {
      tableName: `${prefix}-patient-master`,
      partitionKey: {
        name: 'patient_id',
        type: dynamodb.AttributeType.NUMBER,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Patient Results Table
    const patientResultsTable = new dynamodb.Table(this, 'PatientResultsTable', {
      tableName: `${prefix}-patient-results`,
      partitionKey: {
        name: 'patient_id',
        type: dynamodb.AttributeType.NUMBER,
      },
      sortKey: {
        name: 'report_id',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // GSI for querying pending reports
    patientResultsTable.addGlobalSecondaryIndex({
      indexName: 'report_final_ind-index',
      partitionKey: {
        name: 'report_final_ind',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'created_at',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI for looking up reports by report_id (used by PATCH /reports/update/{report_id})
    patientResultsTable.addGlobalSecondaryIndex({
      indexName: 'report_id-index',
      partitionKey: {
        name: 'report_id',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.KEYS_ONLY,
    });

    // GSI for looking up patient by phone number (for SMS/Twilio integration)
    patientMasterTable.addGlobalSecondaryIndex({
      indexName: 'cell-phone-index',
      partitionKey: {
        name: 'cell_phone',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // Patient Notes Table - for patient-submitted notes via SMS
    const patientNotesTable = new dynamodb.Table(this, 'PatientNotesTable', {
      tableName: `${prefix}-patient-notes`,
      partitionKey: {
        name: 'patient_id',
        type: dynamodb.AttributeType.NUMBER,
      },
      sortKey: {
        name: 'note_id',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // GSI for querying unprocessed notes (like reports/pending)
    patientNotesTable.addGlobalSecondaryIndex({
      indexName: 'processed-index',
      partitionKey: {
        name: 'processed',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'created_at',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI for looking up notes by note_id (used by PATCH /notes/update/{note_id})
    patientNotesTable.addGlobalSecondaryIndex({
      indexName: 'note_id-index',
      partitionKey: {
        name: 'note_id',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.KEYS_ONLY,
    });

    // ==================== Environment Variables ====================
    const lambdaEnv = {
      PATIENT_MASTER_TABLE: patientMasterTable.tableName,
      PATIENT_RESULTS_TABLE: patientResultsTable.tableName,
      PATIENT_NOTES_TABLE: patientNotesTable.tableName,
      REPORTS_BUCKET: reportsBucket.bucketName,
      MEDICAL_IMAGES_BUCKET: medicalImagesBucket.bucketName,
    };

    // Common bundling options
    const bundlingOptions = {
      externalModules: ['@aws-sdk/*'],
      minify: false,
      sourceMap: true,
    };

    // ==================== Lambda Functions ====================

    // GET /patients - List all patients
    const listPatientsLambda = new NodejsFunction(this, 'ListPatientsLambda', {
      functionName: `${prefix}-list-patients`,
      runtime: lambda.Runtime.NODEJS_18_X,
      entry: path.join(__dirname, '../lambda/patients/list/index.js'),
      handler: 'handler',
      environment: lambdaEnv,
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      bundling: bundlingOptions,
    });

    // GET /patients/{id} - Get specific patient
    const getPatientLambda = new NodejsFunction(this, 'GetPatientLambda', {
      functionName: `${prefix}-get-patient`,
      runtime: lambda.Runtime.NODEJS_18_X,
      entry: path.join(__dirname, '../lambda/patients/get/index.js'),
      handler: 'handler',
      environment: lambdaEnv,
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      bundling: bundlingOptions,
    });

    // POST /reports/generate - Generate random report
    const generateReportLambda = new NodejsFunction(this, 'GenerateReportLambda', {
      functionName: `${prefix}-generate-report`,
      runtime: lambda.Runtime.NODEJS_18_X,
      entry: path.join(__dirname, '../lambda/reports/generate/index.js'),
      handler: 'handler',
      environment: lambdaEnv,
      timeout: cdk.Duration.seconds(120),
      memorySize: 1024,
      bundling: {
        ...bundlingOptions,
        // PDFKit needs native modules handling
        nodeModules: ['pdfkit'],
      },
    });

    // GET /reports/{patient_id} - Get reports for patient
    const getReportsLambda = new NodejsFunction(this, 'GetReportsLambda', {
      functionName: `${prefix}-get-reports`,
      runtime: lambda.Runtime.NODEJS_18_X,
      entry: path.join(__dirname, '../lambda/reports/get/index.js'),
      handler: 'handler',
      environment: lambdaEnv,
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      bundling: bundlingOptions,
    });

    // GET /reports/pending - Get pending reports
    const getPendingReportsLambda = new NodejsFunction(this, 'GetPendingReportsLambda', {
      functionName: `${prefix}-get-pending-reports`,
      runtime: lambda.Runtime.NODEJS_18_X,
      entry: path.join(__dirname, '../lambda/reports/pending/index.js'),
      handler: 'handler',
      environment: lambdaEnv,
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      bundling: bundlingOptions,
    });

    // PATCH /reports/{report_id} - Mark report as processed
    const updateReportLambda = new NodejsFunction(this, 'UpdateReportLambda', {
      functionName: `${prefix}-update-report`,
      runtime: lambda.Runtime.NODEJS_18_X,
      entry: path.join(__dirname, '../lambda/reports/update/index.js'),
      handler: 'handler',
      environment: lambdaEnv,
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      bundling: bundlingOptions,
    });

    // Seed Lambda - Populate 100 patients
    const seedLambda = new NodejsFunction(this, 'SeedLambda', {
      functionName: `${prefix}-seed-patients`,
      runtime: lambda.Runtime.NODEJS_18_X,
      entry: path.join(__dirname, '../lambda/seed/index.js'),
      handler: 'handler',
      environment: lambdaEnv,
      timeout: cdk.Duration.seconds(300),
      memorySize: 512,
      bundling: bundlingOptions,
    });

    // Seed Medical Images Lambda - Populate sample images from NIH dataset
    const seedImagesLambda = new NodejsFunction(this, 'SeedImagesLambda', {
      functionName: `${prefix}-seed-medical-images`,
      runtime: lambda.Runtime.NODEJS_18_X,
      entry: path.join(__dirname, '../lambda/seed-images/index.js'),
      handler: 'handler',
      environment: lambdaEnv,
      timeout: cdk.Duration.seconds(900), // 15 minutes for downloading images
      memorySize: 1024,
      bundling: bundlingOptions,
    });

    // ==================== Patient Notes Lambda Functions ====================

    // POST /notes - Receive patient note (Twilio webhook)
    const receiveNoteLambda = new NodejsFunction(this, 'ReceiveNoteLambda', {
      functionName: `${prefix}-receive-note`,
      runtime: lambda.Runtime.NODEJS_18_X,
      entry: path.join(__dirname, '../lambda/notes/receive/index.js'),
      handler: 'handler',
      environment: lambdaEnv,
      timeout: cdk.Duration.seconds(30),
      memorySize: 512,
      bundling: bundlingOptions,
    });

    // Grant Bedrock access for Claude Haiku (vitals extraction)
    receiveNoteLambda.addToRolePolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel'],
      resources: ['arn:aws:bedrock:*::foundation-model/anthropic.claude-3-haiku-*'],
    }));

    // GET /notes/pending - Get unprocessed patient notes
    const getPendingNotesLambda = new NodejsFunction(this, 'GetPendingNotesLambda', {
      functionName: `${prefix}-get-pending-notes`,
      runtime: lambda.Runtime.NODEJS_18_X,
      entry: path.join(__dirname, '../lambda/notes/pending/index.js'),
      handler: 'handler',
      environment: lambdaEnv,
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      bundling: bundlingOptions,
    });

    // PATCH /notes/update/{note_id} - Mark note as processed
    const updateNoteLambda = new NodejsFunction(this, 'UpdateNoteLambda', {
      functionName: `${prefix}-update-note`,
      runtime: lambda.Runtime.NODEJS_18_X,
      entry: path.join(__dirname, '../lambda/notes/update/index.js'),
      handler: 'handler',
      environment: lambdaEnv,
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      bundling: bundlingOptions,
    });

    // POST /notes/generate - Generate sample patient note for testing
    const generateNoteLambda = new NodejsFunction(this, 'GenerateNoteLambda', {
      functionName: `${prefix}-generate-note`,
      runtime: lambda.Runtime.NODEJS_18_X,
      entry: path.join(__dirname, '../lambda/notes/generate/index.js'),
      handler: 'handler',
      environment: lambdaEnv,
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      bundling: bundlingOptions,
    });

    // ==================== Grant Permissions ====================

    // DynamoDB permissions
    patientMasterTable.grantReadData(listPatientsLambda);
    patientMasterTable.grantReadData(getPatientLambda);
    patientMasterTable.grantReadData(generateReportLambda);
    patientMasterTable.grantReadWriteData(seedLambda);

    patientResultsTable.grantReadWriteData(generateReportLambda);
    patientResultsTable.grantReadData(getReportsLambda);
    patientResultsTable.grantReadData(getPendingReportsLambda);
    patientResultsTable.grantReadWriteData(updateReportLambda);

    // S3 permissions - Reports bucket
    reportsBucket.grantReadWrite(generateReportLambda);
    reportsBucket.grantRead(getReportsLambda);
    reportsBucket.grantRead(getPendingReportsLambda);

    // S3 permissions - Medical images bucket
    medicalImagesBucket.grantRead(generateReportLambda);
    medicalImagesBucket.grantReadWrite(seedImagesLambda);

    // Patient Notes permissions
    patientNotesTable.grantReadWriteData(receiveNoteLambda);
    patientNotesTable.grantReadData(getPendingNotesLambda);
    patientNotesTable.grantReadWriteData(updateNoteLambda);
    patientNotesTable.grantReadWriteData(generateNoteLambda);
    patientMasterTable.grantReadData(receiveNoteLambda); // For phone number lookup
    patientMasterTable.grantReadData(generateNoteLambda); // For random patient selection

    // ==================== Pre-Sign Role for Long-Lived URLs ====================
    // Lambda execution role credentials can expire before the pre-signed URL's TTL,
    // causing 403 Forbidden errors. This dedicated role is assumed with an explicit
    // session duration to guarantee the signing credentials outlive the URL's expiresIn.
    const presignRole = new iam.Role(this, 'PresignRole', {
      roleName: `${prefix}-presign-role`,
      assumedBy: new iam.ArnPrincipal(getPendingReportsLambda.role!.roleArn),
      maxSessionDuration: cdk.Duration.hours(5),
    });
    reportsBucket.grantRead(presignRole);

    getPendingReportsLambda.addToRolePolicy(new iam.PolicyStatement({
      actions: ['sts:AssumeRole'],
      resources: [presignRole.roleArn],
    }));
    getPendingReportsLambda.addEnvironment('PRESIGN_ROLE_ARN', presignRole.roleArn);

    // ==================== API Gateway ====================
    const api = new apigateway.RestApi(this, 'MedicalReportsApi', {
      restApiName: `${prefix}-api`,
      description: 'Medical Reports Mock Service API',
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
      },
    });

    // /patients resource
    const patientsResource = api.root.addResource('patients');
    patientsResource.addMethod('GET', new apigateway.LambdaIntegration(listPatientsLambda));

    // /patients/{id} resource
    const patientByIdResource = patientsResource.addResource('{id}');
    patientByIdResource.addMethod('GET', new apigateway.LambdaIntegration(getPatientLambda));

    // /reports resource
    const reportsResource = api.root.addResource('reports');

    // /reports/generate resource
    const generateResource = reportsResource.addResource('generate');
    generateResource.addMethod('POST', new apigateway.LambdaIntegration(generateReportLambda));

    // /reports/generate/{patient_id} resource
    const generateByPatientResource = generateResource.addResource('{patient_id}');
    generateByPatientResource.addMethod('POST', new apigateway.LambdaIntegration(generateReportLambda));

    // /reports/pending resource
    const pendingResource = reportsResource.addResource('pending');
    pendingResource.addMethod('GET', new apigateway.LambdaIntegration(getPendingReportsLambda));

    // /reports/{patient_id} resource (for getting reports by patient)
    const reportsByPatientResource = reportsResource.addResource('{patient_id}');
    reportsByPatientResource.addMethod('GET', new apigateway.LambdaIntegration(getReportsLambda));

    // /reports/update/{report_id} resource
    const updateResource = reportsResource.addResource('update');
    const updateByIdResource = updateResource.addResource('{report_id}');
    updateByIdResource.addMethod('PATCH', new apigateway.LambdaIntegration(updateReportLambda));

    // /seed resource (for populating initial data)
    const seedResource = api.root.addResource('seed');
    seedResource.addMethod('POST', new apigateway.LambdaIntegration(seedLambda));

    // /seed/images resource (for populating medical images from NIH dataset)
    const seedImagesResource = seedResource.addResource('images');
    seedImagesResource.addMethod('POST', new apigateway.LambdaIntegration(seedImagesLambda));

    // ==================== Patient Notes Endpoints ====================

    // /notes resource
    const notesResource = api.root.addResource('notes');

    // POST /notes - Receive patient note from Twilio webhook
    notesResource.addMethod('POST', new apigateway.LambdaIntegration(receiveNoteLambda));

    // /notes/pending - Get unprocessed notes for AI to process
    const pendingNotesResource = notesResource.addResource('pending');
    pendingNotesResource.addMethod('GET', new apigateway.LambdaIntegration(getPendingNotesLambda));

    // /notes/update/{note_id} - Mark note as processed
    const updateNoteResource = notesResource.addResource('update');
    const updateNoteByIdResource = updateNoteResource.addResource('{note_id}');
    updateNoteByIdResource.addMethod('PATCH', new apigateway.LambdaIntegration(updateNoteLambda));

    // /notes/generate - Generate sample patient note for testing
    const generateNoteResource = notesResource.addResource('generate');
    generateNoteResource.addMethod('POST', new apigateway.LambdaIntegration(generateNoteLambda));

    // /notes/generate/{patient_id} - Generate note for specific patient
    const generateNoteByPatientResource = generateNoteResource.addResource('{patient_id}');
    generateNoteByPatientResource.addMethod('POST', new apigateway.LambdaIntegration(generateNoteLambda));

    // ==================== Outputs ====================
    new cdk.CfnOutput(this, 'ApiUrl', {
      value: api.url,
      description: 'API Gateway URL',
    });

    new cdk.CfnOutput(this, 'BucketName', {
      value: reportsBucket.bucketName,
      description: 'S3 Bucket for reports',
    });

    new cdk.CfnOutput(this, 'MedicalImagesBucketName', {
      value: medicalImagesBucket.bucketName,
      description: 'S3 Bucket for real medical images (NIH ChestX-ray14, LIDC, etc.)',
    });

    new cdk.CfnOutput(this, 'PatientMasterTableName', {
      value: patientMasterTable.tableName,
      description: 'Patient Master DynamoDB Table',
    });

    new cdk.CfnOutput(this, 'PatientResultsTableName', {
      value: patientResultsTable.tableName,
      description: 'Patient Results DynamoDB Table',
    });

    new cdk.CfnOutput(this, 'PatientNotesTableName', {
      value: patientNotesTable.tableName,
      description: 'Patient Notes DynamoDB Table (SMS messages from patients)',
    });
  }
}

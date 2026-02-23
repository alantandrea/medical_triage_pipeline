"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || function (mod) {
    if (mod && mod.__esModule) return mod;
    var result = {};
    if (mod != null) for (var k in mod) if (k !== "default" && Object.prototype.hasOwnProperty.call(mod, k)) __createBinding(result, mod, k);
    __setModuleDefault(result, mod);
    return result;
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.MedicalReportsServiceStack = void 0;
const cdk = __importStar(require("aws-cdk-lib"));
const dynamodb = __importStar(require("aws-cdk-lib/aws-dynamodb"));
const s3 = __importStar(require("aws-cdk-lib/aws-s3"));
const lambda = __importStar(require("aws-cdk-lib/aws-lambda"));
const aws_lambda_nodejs_1 = require("aws-cdk-lib/aws-lambda-nodejs");
const apigateway = __importStar(require("aws-cdk-lib/aws-apigateway"));
const iam = __importStar(require("aws-cdk-lib/aws-iam"));
const path = __importStar(require("path"));
class MedicalReportsServiceStack extends cdk.Stack {
    constructor(scope, id, props) {
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
        const listPatientsLambda = new aws_lambda_nodejs_1.NodejsFunction(this, 'ListPatientsLambda', {
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
        const getPatientLambda = new aws_lambda_nodejs_1.NodejsFunction(this, 'GetPatientLambda', {
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
        const generateReportLambda = new aws_lambda_nodejs_1.NodejsFunction(this, 'GenerateReportLambda', {
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
        const getReportsLambda = new aws_lambda_nodejs_1.NodejsFunction(this, 'GetReportsLambda', {
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
        const getPendingReportsLambda = new aws_lambda_nodejs_1.NodejsFunction(this, 'GetPendingReportsLambda', {
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
        const updateReportLambda = new aws_lambda_nodejs_1.NodejsFunction(this, 'UpdateReportLambda', {
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
        const seedLambda = new aws_lambda_nodejs_1.NodejsFunction(this, 'SeedLambda', {
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
        const seedImagesLambda = new aws_lambda_nodejs_1.NodejsFunction(this, 'SeedImagesLambda', {
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
        const receiveNoteLambda = new aws_lambda_nodejs_1.NodejsFunction(this, 'ReceiveNoteLambda', {
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
        const getPendingNotesLambda = new aws_lambda_nodejs_1.NodejsFunction(this, 'GetPendingNotesLambda', {
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
        const updateNoteLambda = new aws_lambda_nodejs_1.NodejsFunction(this, 'UpdateNoteLambda', {
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
        const generateNoteLambda = new aws_lambda_nodejs_1.NodejsFunction(this, 'GenerateNoteLambda', {
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
exports.MedicalReportsServiceStack = MedicalReportsServiceStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoibWVkaWNhbF9yZXBvcnRzLXNlcnZpY2Utc3RhY2suanMiLCJzb3VyY2VSb290IjoiIiwic291cmNlcyI6WyJtZWRpY2FsX3JlcG9ydHMtc2VydmljZS1zdGFjay50cyJdLCJuYW1lcyI6W10sIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUVuQyxtRUFBcUQ7QUFDckQsdURBQXlDO0FBQ3pDLCtEQUFpRDtBQUNqRCxxRUFBK0Q7QUFDL0QsdUVBQXlEO0FBQ3pELHlEQUEyQztBQUMzQywyQ0FBNkI7QUFFN0IsTUFBYSwwQkFBMkIsU0FBUSxHQUFHLENBQUMsS0FBSztJQUN2RCxZQUFZLEtBQWdCLEVBQUUsRUFBVSxFQUFFLEtBQXNCO1FBQzlELEtBQUssQ0FBQyxLQUFLLEVBQUUsRUFBRSxFQUFFLEtBQUssQ0FBQyxDQUFDO1FBRXhCLE1BQU0sTUFBTSxHQUFHLG9CQUFvQixDQUFDO1FBRXBDLHVEQUF1RDtRQUV2RCxzQ0FBc0M7UUFDdEMsTUFBTSxhQUFhLEdBQUcsSUFBSSxFQUFFLENBQUMsTUFBTSxDQUFDLElBQUksRUFBRSxlQUFlLEVBQUU7WUFDekQsVUFBVSxFQUFFLEdBQUcsTUFBTSxZQUFZLElBQUksQ0FBQyxPQUFPLEVBQUU7WUFDL0MsYUFBYSxFQUFFLEdBQUcsQ0FBQyxhQUFhLENBQUMsT0FBTztZQUN4QyxpQkFBaUIsRUFBRSxJQUFJO1lBQ3ZCLElBQUksRUFBRTtnQkFDSjtvQkFDRSxjQUFjLEVBQUUsQ0FBQyxFQUFFLENBQUMsV0FBVyxDQUFDLEdBQUcsRUFBRSxFQUFFLENBQUMsV0FBVyxDQUFDLEdBQUcsQ0FBQztvQkFDeEQsY0FBYyxFQUFFLENBQUMsR0FBRyxDQUFDO29CQUNyQixjQUFjLEVBQUUsQ0FBQyxHQUFHLENBQUM7aUJBQ3RCO2FBQ0Y7U0FDRixDQUFDLENBQUM7UUFFSCx3RUFBd0U7UUFDeEUsTUFBTSxtQkFBbUIsR0FBRyxJQUFJLEVBQUUsQ0FBQyxNQUFNLENBQUMsSUFBSSxFQUFF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QUNoQyxLQUFLLEVBQUUsR0FBRyxDQUFDLEdBQUc7WUFDZCxXQUFXLEVBQUUsaUJBQWlCO1NBQy9CLENBQUMsQ0FBQztRQUVILElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsWUFBWSxFQUFFO1lBQ3BDLEtBQUssRUFBRSxhQUFhLENBQUMsVUFBVTtZQUMvQixXQUFXLEVBQUUsdUJBQXVCO1NBQ3JDLENBQUMsQ0FBQztRQUVILElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUseUJBQXlCLEVBQUU7WUFDakQsS0FBSyxFQUFFLG1CQUFtQixDQUFDLFVBQVU7WUFDckMsV0FBVyxFQUFFLGtFQUFrRTtTQUNoRixDQUFDLENBQUM7UUFFSCxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLHdCQUF3QixFQUFFO1lBQ2hELEtBQUssRUFBRSxrQkFBa0IsQ0FBQyxTQUFTO1lBQ25DLFdBQVcsRUFBRSwrQkFBK0I7U0FDN0MsQ0FBQyxDQUFDO1FBRUgsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSx5QkFBeUIsRUFBRTtZQUNqRCxLQUFLLEVBQUUsbUJBQW1CLENBQUMsU0FBUztZQUNwQyxXQUFXLEVBQUUsZ0NBQWdDO1NBQzlDLENBQUMsQ0FBQztRQUVILElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsdUJBQXVCLEVBQUU7WUFDL0MsS0FBSyxFQUFFLGlCQUFpQixDQUFDLFNBQVM7WUFDbEMsV0FBVyxFQUFFLDJEQUEyRDtTQUN6RSxDQUFDLENBQUM7SUFDTCxDQUFDO0NBQ0Y7QUEzYUQsZ0VBMmFDIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCB7IENvbnN0cnVjdCB9IGZyb20gJ2NvbnN0cnVjdHMnO1xuaW1wb3J0ICogYXMgZHluYW1vZGIgZnJvbSAnYXdzLWNkay1saWIvYXdzLWR5bmFtb2RiJztcbmltcG9ydCAqIGFzIHMzIGZyb20gJ2F3cy1jZGstbGliL2F3cy1zMyc7XG5pbXBvcnQgKiBhcyBsYW1iZGEgZnJvbSAnYXdzLWNkay1saWIvYXdzLWxhbWJkYSc7XG5pbXBvcnQgeyBOb2RlanNGdW5jdGlvbiB9IGZyb20gJ2F3cy1jZGstbGliL2F3cy1sYW1iZGEtbm9kZWpzJztcbmltcG9ydCAqIGFzIGFwaWdhdGV3YXkgZnJvbSAnYXdzLWNkay1saWIvYXdzLWFwaWdhdGV3YXknO1xuaW1wb3J0ICogYXMgaWFtIGZyb20gJ2F3cy1jZGstbGliL2F3cy1pYW0nO1xuaW1wb3J0ICogYXMgcGF0aCBmcm9tICdwYXRoJztcblxuZXhwb3J0IGNsYXNzIE1lZGljYWxSZXBvcnRzU2VydmljZVN0YWNrIGV4dGVuZHMgY2RrLlN0YWNrIHtcbiAgY29uc3RydWN0b3Ioc2NvcGU6IENvbnN0cnVjdCwgaWQ6IHN0cmluZywgcHJvcHM/OiBjZGsuU3RhY2tQcm9wcykge1xuICAgIHN1cGVyKHNjb3BlLCBpZCwgcHJvcHMpO1xuXG4gICAgY29uc3QgcHJlZml4ID0gJ21lZGdlbW1hLWNoYWxsZW5nZSc7XG5cbiAgICAvLyA9PT09PT09PT09PT09PT09PT09PSBTMyBCdWNrZXRzID09PT09PT09PT09PT09PT09PT09XG5cbiAgICAvLyBCdWNrZXQgZm9yIGdlbmVyYXRlZCByZXBvcnRzIChQREZzKVxuICAgIGNvbnN0IHJlcG9ydHNCdWNrZXQgPSBuZXcgczMuQnVja2V0KHRoaXMsICdSZXBvcnRzQnVja2V0Jywge1xuICAgICAgYnVja2V0TmFtZTogYCR7cHJlZml4fS1yZXBvcnRzLSR7dGhpcy5hY2NvdW50fWAsXG4gICAgICByZW1vdmFsUG9saWN5OiBjZGsuUmVtb3ZhbFBvbGljeS5ERVNUUk9ZLFxuICAgICAgYXV0b0RlbGV0ZU9iamVjdHM6IHRydWUsXG4gICAgICBjb3JzOiBbXG4gICAgICAgIHtcbiAgICAgICAgICBhbGxvd2VkTWV0aG9kczogW3MzLkh0dHBNZXRob2RzLkdFVCwgczMuSHR0cE1ldGhvZHMuUFVUXSxcbiAgICAgICAgICBhbGxvd2VkT3JpZ2luczogWycqJ10sXG4gICAgICAgICAgYWxsb3dlZEhlYWRlcnM6IFsnKiddLFxuICAgICAgICB9LFxuICAgICAgXSxcbiAgICB9KTtcblxuICAgIC8vIEJ1Y2tldCBmb3IgcmVhbCBtZWRpY2FsIGltYWdlcyBmcm9tIHB1YmxpYyBkYXRhc2V0cyAoTklILCBMSURDLCBldGMuKVxuICAgIGNvbnN0IG1lZGljYWxJbWFnZXNCdWNrZXQgPSBuZXcgczMuQnVja2V0KHRoaXMsICdNZWRpY2FsSW1hZ2VzQnVja2V0Jywge1xuICAgICAgYnVja2V0TmFtZTogYCR7cHJlZml4fS1tZWRpY2FsLWltYWdlcy0ke3RoaXMuYWNjb3VudH1gLFxuICAgICAgcmVtb3ZhbFBvbGljeTogY2RrLlJlbW92YWxQb2xpY3kuREVTVFJPWSxcbiAgICAgIGF1dG9EZWxldGVPYmplY3RzOiB0cnVlLFxuICAgICAgY29yczogW1xuICAgICAgICB7XG4gICAgICAgICAgYWxsb3dlZE1ldGhvZHM6IFtzMy5IdHRwTWV0aG9kcy5HRVQsIHMzLkh0dHBNZXRob2RzLlBVVF0sXG4gICAgICAgICAgYWxsb3dlZE9yaWdpbnM6IFsnKiddLFxuICAgICAgICAgIGFsbG93ZWRIZWFkZXJzOiBbJyonXSxcbiAgICAgICAgfSxcbiAgICAgIF0sXG4gICAgfSk7XG5cbiAgICAvLyA9PT09PT09PT09PT09PT09PT09PSBEeW5hbW9EQiBUYWJsZXMgPT09PT09PT09PT09PT09PT09PT1cblxuICAgIC8vIFBhdGllbnQgTWFzdGVyIFRhYmxlXG4gICAgY29uc3QgcGF0aWVudE1hc3RlclRhYmxlID0gbmV3IGR5bmFtb2RiLlRhYmxlKHRoaXMsICdQYXRpZW50TWFzdGVyVGFibGUnLCB7XG4gICAgICB0YWJsZU5hbWU6IGAke3ByZWZpeH0tcGF0aWVudC1tYXN0ZXJgLFxuICAgICAgcGFydGl0aW9uS2V5OiB7XG4gICAgICAgIG5hbWU6ICdwYXRpZW50X2lkJyxcbiAgICAgICAgdHlwZTogZHluYW1vZGIuQXR0cmlidXRlVHlwZS5OVU1CRVIsXG4gICAgICB9LFxuICAgICAgYmlsbGluZ01vZGU6IGR5bmFtb2RiLkJpbGxpbmdNb2RlLlBBWV9QRVJfUkVRVUVTVCxcbiAgICAgIHJlbW92YWxQb2xpY3k6IGNkay5SZW1vdmFsUG9saWN5LkRFU1RST1ksXG4gICAgfSk7XG5cbiAgICAvLyBQYXRpZW50IFJlc3VsdHMgVGFibGVcbiAgICBjb25zdCBwYXRpZW50UmVzdWx0c1RhYmxlID0gbmV3IGR5bmFtb2RiLlRhYmxlKHRoaXMsICdQYXRpZW50UmVzdWx0c1RhYmxlJywge1xuICAgICAgdGFibGVOYW1lOiBgJHtwcmVmaXh9LXBhdGllbnQtcmVzdWx0c2AsXG4gICAgICBwYXJ0aXRpb25LZXk6IHtcbiAgICAgICAgbmFtZTogJ3BhdGllbnRfaWQnLFxuICAgICAgICB0eXBlOiBkeW5hbW9kYi5BdHRyaWJ1dGVUeXBlLk5VTUJFUixcbiAgICAgIH0sXG4gICAgICBzb3J0S2V5OiB7XG4gICAgICAgIG5hbWU6ICdyZXBvcnRfaWQnLFxuICAgICAgICB0eXBlOiBkeW5hbW9kYi5BdHRyaWJ1dGVUeXBlLlNUUklORyxcbiAgICAgIH0sXG4gICAgICBiaWxsaW5nTW9kZTogZHluYW1vZGIuQmlsbGluZ01vZGUuUEFZX1BFUl9SRVFVRVNULFxuICAgICAgcmVtb3ZhbFBvbGljeTogY2RrLlJlbW92YWxQb2xpY3kuREVTVFJPWSxcbiAgICB9KTtcblxuICAgIC8vIEdTSSBmb3IgcXVlcnlpbmcgcGVuZGluZyByZXBvcnRzXG4gICAgcGF0aWVudFJlc3VsdHNUYWJsZS5hZGRHbG9iYWxTZWNvbmRhcnlJbmRleCh7XG4gICAgICBpbmRleE5hbWU6ICdyZXBvcnRfZmluYWxfaW5kLWluZGV4JyxcbiAgICAgIHBhcnRpdGlvbktleToge1xuICAgICAgICBuYW1lOiAncmVwb3J0X2ZpbmFsX2luZCcsXG4gICAgICAgIHR5cGU6IGR5bmFtb2RiLkF0dHJpYnV0ZVR5cGUuU1RSSU5HLFxuICAgICAgfSxcbiAgICAgIHNvcnRLZXk6IHtcbiAgICAgICAgbmFtZTogJ2NyZWF0ZWRfYXQnLFxuICAgICAgICB0eXBlOiBkeW5hbW9kYi5BdHRyaWJ1dGVUeXBlLlNUUklORyxcbiAgICAgIH0sXG4gICAgICBwcm9qZWN0aW9uVHlwZTogZHluYW1vZGIuUHJvamVjdGlvblR5cGUuQUxMLFxuICAgIH0pO1xuXG4gICAgLy8gR1NJIGZvciBsb29raW5nIHVwIHBhdGllbnQgYnkgcGhvbmUgbnVtYmVyIChmb3IgU01TL1R3aWxpbyBpbnRlZ3JhdGlvbilcbiAgICBwYXRpZW50TWFzdGVyVGFibGUuYWRkR2xvYmFsU2Vjb25kYXJ5SW5kZXgoe1xuICAgICAgaW5kZXhOYW1lOiAnY2VsbC1waG9uZS1pbmRleCcsXG4gICAgICBwYXJ0aXRpb25LZXk6IHtcbiAgICAgICAgbmFtZTogJ2NlbGxfcGhvbmUnLFxuICAgICAgICB0eXBlOiBkeW5hbW9kYi5BdHRyaWJ1dGVUeXBlLlNUUklORyxcbiAgICAgIH0sXG4gICAgICBwcm9qZWN0aW9uVHlwZTogZHluYW1vZGIuUHJvamVjdGlvblR5cGUuQUxMLFxuICAgIH0pO1xuXG4gICAgLy8gUGF0aWVudCBOb3RlcyBUYWJsZSAtIGZvciBwYXRpZW50LXN1Ym1pdHRlZCBub3RlcyB2aWEgU01TXG4gICAgY29uc3QgcGF0aWVudE5vdGVzVGFibGUgPSBuZXcgZHluYW1vZGIuVGFibGUodGhpcywgJ1BhdGllbnROb3Rlc1RhYmxlJywge1xuICAgICAgdGFibGVOYW1lOiBgJHtwcmVmaXh9LXBhdGllbnQtbm90ZXNgLFxuICAgICAgcGFydGl0aW9uS2V5OiB7XG4gICAgICAgIG5hbWU6ICdwYXRpZW50X2lkJyxcbiAgICAgICAgdHlwZTogZHluYW1vZGIuQXR0cmlidXRlVHlwZS5OVU1CRVIsXG4gICAgICB9LFxuICAgICAgc29ydEtleToge1xuICAgICAgICBuYW1lOiAnbm90ZV9pZCcsXG4gICAgICAgIHR5cGU6IGR5bmFtb2RiLkF0dHJpYnV0ZVR5cGUuU1RSSU5HLFxuICAgICAgfSxcbiAgICAgIGJpbGxpbmdNb2RlOiBkeW5hbW9kYi5CaWxsaW5nTW9kZS5QQVlfUEVSX1JFUVVFU1QsXG4gICAgICByZW1vdmFsUG9saWN5OiBjZGsuUmVtb3ZhbFBvbGljeS5ERVNUUk9ZLFxuICAgIH0pO1xuXG4gICAgLy8gR1NJIGZvciBxdWVyeWluZyB1bnByb2Nlc3NlZCBub3RlcyAobGlrZSByZXBvcnRzL3BlbmRpbmcpXG4gICAgcGF0aWVudE5vdGVzVGFibGUuYWRkR2xvYmFsU2Vjb25kYXJ5SW5kZXgoe1xuICAgICAgaW5kZXhOYW1lOiAncHJvY2Vzc2VkLWluZGV4JyxcbiAgICAgIHBhcnRpdGlvbktleToge1xuICAgICAgICBuYW1lOiAncHJvY2Vzc2VkJyxcbiAgICAgICAgdHlwZTogZHluYW1vZGIuQXR0cmlidXRlVHlwZS5TVFJJTkcsXG4gICAgICB9LFxuICAgICAgc29ydEtleToge1xuICAgICAgICBuYW1lOiAnY3JlYXRlZF9hdCcsXG4gICAgICAgIHR5cGU6IGR5bmFtb2RiLkF0dHJpYnV0ZVR5cGUuU1RSSU5HLFxuICAgICAgfSxcbiAgICAgIHByb2plY3Rpb25UeXBlOiBkeW5hbW9kYi5Qcm9qZWN0aW9uVHlwZS5BTEwsXG4gICAgfSk7XG5cbiAgICAvLyA9PT09PT09PT09PT09PT09PT09PSBFbnZpcm9ubWVudCBWYXJpYWJsZXMgPT09PT09PT09PT09PT09PT09PT1cbiAgICBjb25zdCBsYW1iZGFFbnYgPSB7XG4gICAgICBQQVRJRU5UX01BU1RFUl9UQUJMRTogcGF0aWVudE1hc3RlclRhYmxlLnRhYmxlTmFtZSxcbiAgICAgIFBBVElFTlRfUkVTVUxUU19UQUJMRTogcGF0aWVudFJlc3VsdHNUYWJsZS50YWJsZU5hbWUsXG4gICAgICBQQVRJRU5UX05PVEVTX1RBQkxFOiBwYXRpZW50Tm90ZXNUYWJsZS50YWJsZU5hbWUsXG4gICAgICBSRVBPUlRTX0JVQ0tFVDogcmVwb3J0c0J1Y2tldC5idWNrZXROYW1lLFxuICAgICAgTUVESUNBTF9JTUFHRVNfQlVDS0VUOiBtZWRpY2FsSW1hZ2VzQnVja2V0LmJ1Y2tldE5hbWUsXG4gICAgfTtcblxuICAgIC8vIENvbW1vbiBidW5kbGluZyBvcHRpb25zXG4gICAgY29uc3QgYnVuZGxpbmdPcHRpb25zID0ge1xuICAgICAgZXh0ZXJuYWxNb2R1bGVzOiBbJ0Bhd3Mtc2RrLyonXSxcbiAgICAgIG1pbmlmeTogZmFsc2UsXG4gICAgICBzb3VyY2VNYXA6IHRydWUsXG4gICAgfTtcblxuICAgIC8vID09PT09PT09PT09PT09PT09PT09IExhbWJkYSBGdW5jdGlvbnMgPT09PT09PT09PT09PT09PT09PT1cblxuICAgIC8vIEdFVCAvcGF0aWVudHMgLSBMaXN0IGFsbCBwYXRpZW50c1xuICAgIGNvbnN0IGxpc3RQYXRpZW50c0xhbWJkYSA9IG5ldyBOb2RlanNGdW5jdGlvbih0aGlzLCAnTGlzdFBhdGllbnRzTGFtYmRhJywge1xuICAgICAgZnVuY3Rpb25OYW1lOiBgJHtwcmVmaXh9LWxpc3QtcGF0aWVudHNgLFxuICAgICAgcnVudGltZTogbGFtYmRhLlJ1bnRpbWUuTk9ERUpTXzE4X1gsXG4gICAgICBlbnRyeTogcGF0aC5qb2luKF9fZGlybmFtZSwgJy4uL2xhbWJkYS9wYXRpZW50cy9saXN0L2luZGV4LmpzJyksXG4gICAgICBoYW5kbGVyOiAnaGFuZGxlcicsXG4gICAgICBlbnZpcm9ubWVudDogbGFtYmRhRW52LFxuICAgICAgdGltZW91dDogY2RrLkR1cmF0aW9uLnNlY29uZHMoMzApLFxuICAgICAgbWVtb3J5U2l6ZTogMjU2LFxuICAgICAgYnVuZGxpbmc6IGJ1bmRsaW5nT3B0aW9ucyxcbiAgICB9KTtcblxuICAgIC8vIEdFVCAvcGF0aWVudHMve2lkfSAtIEdldCBzcGVjaWZpYyBwYXRpZW50XG4gICAgY29uc3QgZ2V0UGF0aWVudExhbWJkYSA9IG5ldyBOb2RlanNGdW5jdGlvbih0aGlzLCAnR2V0UGF0aWVudExhbWJkYScsIHtcbiAgICAgIGZ1bmN0aW9uTmFtZTogYCR7cHJlZml4fS1nZXQtcGF0aWVudGAsXG4gICAgICBydW50aW1lOiBsYW1iZGEuUnVudGltZS5OT0RFSlNfMThfWCxcbiAgICAgIGVudHJ5OiBwYXRoLmpvaW4oX19kaXJuYW1lLCAnLi4vbGFtYmRhL3BhdGllbnRzL2dldC9pbmRleC5qcycpLFxuICAgICAgaGFuZGxlcjogJ2hhbmRsZXInLFxuICAgICAgZW52aXJvbm1lbnQ6IGxhbWJkYUVudixcbiAgICAgIHRpbWVvdXQ6IGNkay5EdXJhdGlvbi5zZWNvbmRzKDMwKSxcbiAgICAgIG1lbW9yeVNpemU6IDI1NixcbiAgICAgIGJ1bmRsaW5nOiBidW5kbGluZ09wdGlvbnMsXG4gICAgfSk7XG5cbiAgICAvLyBQT1NUIC9yZXBvcnRzL2dlbmVyYXRlIC0gR2VuZXJhdGUgcmFuZG9tIHJlcG9ydFxuICAgIGNvbnN0IGdlbmVyYXRlUmVwb3J0TGFtYmRhID0gbmV3IE5vZGVqc0Z1bmN0aW9uKHRoaXMsICdHZW5lcmF0ZVJlcG9ydExhbWJkYScsIHtcbiAgICAgIGZ1bmN0aW9uTmFtZTogYCR7cHJlZml4fS1nZW5lcmF0ZS1yZXBvcnRgLFxuICAgICAgcnVudGltZTogbGFtYmRhLlJ1bnRpbWUuTk9ERUpTXzE4X1gsXG4gICAgICBlbnRyeTogcGF0aC5qb2luKF9fZGlybmFtZSwgJy4uL2xhbWJkYS9yZXBvcnRzL2dlbmVyYXRlL2luZGV4LmpzJyksXG4gICAgICBoYW5kbGVyOiAnaGFuZGxlcicsXG4gICAgICBlbnZpcm9ubWVudDogbGFtYmRhRW52LFxuICAgICAgdGltZW91dDogY2RrLkR1cmF0aW9uLnNlY29uZHMoMTIwKSxcbiAgICAgIG1lbW9yeVNpemU6IDEwMjQsXG4gICAgICBidW5kbGluZzoge1xuICAgICAgICAuLi5idW5kbGluZ09wdGlvbnMsXG4gICAgICAgIC8vIFBERktpdCBuZWVkcyBuYXRpdmUgbW9kdWxlcyBoYW5kbGluZ1xuICAgICAgICBub2RlTW9kdWxlczogWydwZGZraXQnXSxcbiAgICAgIH0sXG4gICAgfSk7XG5cbiAgICAvLyBHRVQgL3JlcG9ydHMve3BhdGllbnRfaWR9IC0gR2V0IHJlcG9ydHMgZm9yIHBhdGllbnRcbiAgICBjb25zdCBnZXRSZXBvcnRzTGFtYmRhID0gbmV3IE5vZGVqc0Z1bmN0aW9uKHRoaXMsICdHZXRSZXBvcnRzTGFtYmRhJywge1xuICAgICAgZnVuY3Rpb25OYW1lOiBgJHtwcmVmaXh9LWdldC1yZXBvcnRzYCxcbiAgICAgIHJ1bnRpbWU6IGxhbWJkYS5SdW50aW1lLk5PREVKU18xOF9YLFxuICAgICAgZW50cnk6IHBhdGguam9pbihfX2Rpcm5hbWUsICcuLi9sYW1iZGEvcmVwb3J0cy9nZXQvaW5kZXguanMnKSxcbiAgICAgIGhhbmRsZXI6ICdoYW5kbGVyJyxcbiAgICAgIGVudmlyb25tZW50OiBsYW1iZGFFbnYsXG4gICAgICB0aW1lb3V0OiBjZGsuRHVyYXRpb24uc2Vjb25kcygzMCksXG4gICAgICBtZW1vcnlTaXplOiAyNTYsXG4gICAgICBidW5kbGluZzogYnVuZGxpbmdPcHRpb25zLFxuICAgIH0pO1xuXG4gICAgLy8gR0VUIC9yZXBvcnRzL3BlbmRpbmcgLSBHZXQgcGVuZGluZyByZXBvcnRzXG4gICAgY29uc3QgZ2V0UGVuZGluZ1JlcG9ydHNMYW1iZGEgPSBuZXcgTm9kZWpzRnVuY3Rpb24odGhpcywgJ0dldFBlbmRpbmdSZXBvcnRzTGFtYmRhJywge1xuICAgICAgZnVuY3Rpb25OYW1lOiBgJHtwcmVmaXh9LWdldC1wZW5kaW5nLXJlcG9ydHNgLFxuICAgICAgcnVudGltZTogbGFtYmRhLlJ1bnRpbWUuTk9ERUpTXzE4X1gsXG4gICAgICBlbnRyeTogcGF0aC5qb2luKF9fZGlybmFtZSwgJy4uL2xhbWJkYS9yZXBvcnRzL3BlbmRpbmcvaW5kZXguanMnKSxcbiAgICAgIGhhbmRsZXI6ICdoYW5kbGVyJyxcbiAgICAgIGVudmlyb25tZW50OiBsYW1iZGFFbnYsXG4gICAgICB0aW1lb3V0OiBjZGsuRHVyYXRpb24uc2Vjb25kcygzMCksXG4gICAgICBtZW1vcnlTaXplOiAyNTYsXG4gICAgICBidW5kbGluZzogYnVuZGxpbmdPcHRpb25zLFxuICAgIH0pO1xuXG4gICAgLy8gUEFUQ0ggL3JlcG9ydHMve3JlcG9ydF9pZH0gLSBNYXJrIHJlcG9ydCBhcyBwcm9jZXNzZWRcbiAgICBjb25zdCB1cGRhdGVSZXBvcnRMYW1iZGEgPSBuZXcgTm9kZWpzRnVuY3Rpb24odGhpcywgJ1VwZGF0ZVJlcG9ydExhbWJkYScsIHtcbiAgICAgIGZ1bmN0aW9uTmFtZTogYCR7cHJlZml4fS11cGRhdGUtcmVwb3J0YCxcbiAgICAgIHJ1bnRpbWU6IGxhbWJkYS5SdW50aW1lLk5PREVKU18xOF9YLFxuICAgICAgZW50cnk6IHBhdGguam9pbihfX2Rpcm5hbWUsICcuLi9sYW1iZGEvcmVwb3J0cy91cGRhdGUvaW5kZXguanMnKSxcbiAgICAgIGhhbmRsZXI6ICdoYW5kbGVyJyxcbiAgICAgIGVudmlyb25tZW50OiBsYW1iZGFFbnYsXG4gICAgICB0aW1lb3V0OiBjZGsuRHVyYXRpb24uc2Vjb25kcygzMCksXG4gICAgICBtZW1vcnlTaXplOiAyNTYsXG4gICAgICBidW5kbGluZzogYnVuZGxpbmdPcHRpb25zLFxuICAgIH0pO1xuXG4gICAgLy8gU2VlZCBMYW1iZGEgLSBQb3B1bGF0ZSAxMDAgcGF0aWVudHNcbiAgICBjb25zdCBzZWVkTGFtYmRhID0gbmV3IE5vZGVqc0Z1bmN0aW9uKHRoaXMsICdTZWVkTGFtYmRhJywge1xuICAgICAgZnVuY3Rpb25OYW1lOiBgJHtwcmVmaXh9LXNlZWQtcGF0aWVudHNgLFxuICAgICAgcnVudGltZTogbGFtYmRhLlJ1bnRpbWUuTk9ERUpTXzE4X1gsXG4gICAgICBlbnRyeTogcGF0aC5qb2luKF9fZGlybmFtZSwgJy4uL2xhbWJkYS9zZWVkL2luZGV4LmpzJyksXG4gICAgICBoYW5kbGVyOiAnaGFuZGxlcicsXG4gICAgICBlbnZpcm9ubWVudDogbGFtYmRhRW52LFxuICAgICAgdGltZW91dDogY2RrLkR1cmF0aW9uLnNlY29uZHMoMzAwKSxcbiAgICAgIG1lbW9yeVNpemU6IDUxMixcbiAgICAgIGJ1bmRsaW5nOiBidW5kbGluZ09wdGlvbnMsXG4gICAgfSk7XG5cbiAgICAvLyBTZWVkIE1lZGljYWwgSW1hZ2VzIExhbWJkYSAtIFBvcHVsYXRlIHNhbXBsZSBpbWFnZXMgZnJvbSBOSUggZGF0YXNldFxuICAgIGNvbnN0IHNlZWRJbWFnZXNMYW1iZGEgPSBuZXcgTm9kZWpzRnVuY3Rpb24odGhpcywgJ1NlZWRJbWFnZXNMYW1iZGEnLCB7XG4gICAgICBmdW5jdGlvbk5hbWU6IGAke3ByZWZpeH0tc2VlZC1tZWRpY2FsLWltYWdlc2AsXG4gICAgICBydW50aW1lOiBsYW1iZGEuUnVudGltZS5OT0RFSlNfMThfWCxcbiAgICAgIGVudHJ5OiBwYXRoLmpvaW4oX19kaXJuYW1lLCAnLi4vbGFtYmRhL3NlZWQtaW1hZ2VzL2luZGV4LmpzJyksXG4gICAgICBoYW5kbGVyOiAnaGFuZGxlcicsXG4gICAgICBlbnZpcm9ubWVudDogbGFtYmRhRW52LFxuICAgICAgdGltZW91dDogY2RrLkR1cmF0aW9uLnNlY29uZHMoOTAwKSwgLy8gMTUgbWludXRlcyBmb3IgZG93bmxvYWRpbmcgaW1hZ2VzXG4gICAgICBtZW1vcnlTaXplOiAxMDI0LFxuICAgICAgYnVuZGxpbmc6IGJ1bmRsaW5nT3B0aW9ucyxcbiAgICB9KTtcblxuICAgIC8vID09PT09PT09PT09PT09PT09PT09IFBhdGllbnQgTm90ZXMgTGFtYmRhIEZ1bmN0aW9ucyA9PT09PT09PT09PT09PT09PT09PVxuXG4gICAgLy8gUE9TVCAvbm90ZXMgLSBSZWNlaXZlIHBhdGllbnQgbm90ZSAoVHdpbGlvIHdlYmhvb2spXG4gICAgY29uc3QgcmVjZWl2ZU5vdGVMYW1iZGEgPSBuZXcgTm9kZWpzRnVuY3Rpb24odGhpcywgJ1JlY2VpdmVOb3RlTGFtYmRhJywge1xuICAgICAgZnVuY3Rpb25OYW1lOiBgJHtwcmVmaXh9LXJlY2VpdmUtbm90ZWAsXG4gICAgICBydW50aW1lOiBsYW1iZGEuUnVudGltZS5OT0RFSlNfMThfWCxcbiAgICAgIGVudHJ5OiBwYXRoLmpvaW4oX19kaXJuYW1lLCAnLi4vbGFtYmRhL25vdGVzL3JlY2VpdmUvaW5kZXguanMnKSxcbiAgICAgIGhhbmRsZXI6ICdoYW5kbGVyJyxcbiAgICAgIGVudmlyb25tZW50OiBsYW1iZGFFbnYsXG4gICAgICB0aW1lb3V0OiBjZGsuRHVyYXRpb24uc2Vjb25kcygzMCksXG4gICAgICBtZW1vcnlTaXplOiA1MTIsXG4gICAgICBidW5kbGluZzogYnVuZGxpbmdPcHRpb25zLFxuICAgIH0pO1xuXG4gICAgLy8gR3JhbnQgQmVkcm9jayBhY2Nlc3MgZm9yIENsYXVkZSBIYWlrdSAodml0YWxzIGV4dHJhY3Rpb24pXG4gICAgcmVjZWl2ZU5vdGVMYW1iZGEuYWRkVG9Sb2xlUG9saWN5KG5ldyBpYW0uUG9saWN5U3RhdGVtZW50KHtcbiAgICAgIGFjdGlvbnM6IFsnYmVkcm9jazpJbnZva2VNb2RlbCddLFxuICAgICAgcmVzb3VyY2VzOiBbJ2Fybjphd3M6YmVkcm9jazoqOjpmb3VuZGF0aW9uLW1vZGVsL2FudGhyb3BpYy5jbGF1ZGUtMy1oYWlrdS0qJ10sXG4gICAgfSkpO1xuXG4gICAgLy8gR0VUIC9ub3Rlcy9wZW5kaW5nIC0gR2V0IHVucHJvY2Vzc2VkIHBhdGllbnQgbm90ZXNcbiAgICBjb25zdCBnZXRQZW5kaW5nTm90ZXNMYW1iZGEgPSBuZXcgTm9kZWpzRnVuY3Rpb24odGhpcywgJ0dldFBlbmRpbmdOb3Rlc0xhbWJkYScsIHtcbiAgICAgIGZ1bmN0aW9uTmFtZTogYCR7cHJlZml4fS1nZXQtcGVuZGluZy1ub3Rlc2AsXG4gICAgICBydW50aW1lOiBsYW1iZGEuUnVudGltZS5OT0RFSlNfMThfWCxcbiAgICAgIGVudHJ5OiBwYXRoLmpvaW4oX19kaXJuYW1lLCAnLi4vbGFtYmRhL25vdGVzL3BlbmRpbmcvaW5kZXguanMnKSxcbiAgICAgIGhhbmRsZXI6ICdoYW5kbGVyJyxcbiAgICAgIGVudmlyb25tZW50OiBsYW1iZGFFbnYsXG4gICAgICB0aW1lb3V0OiBjZGsuRHVyYXRpb24uc2Vjb25kcygzMCksXG4gICAgICBtZW1vcnlTaXplOiAyNTYsXG4gICAgICBidW5kbGluZzogYnVuZGxpbmdPcHRpb25zLFxuICAgIH0pO1xuXG4gICAgLy8gUEFUQ0ggL25vdGVzL3VwZGF0ZS97bm90ZV9pZH0gLSBNYXJrIG5vdGUgYXMgcHJvY2Vzc2VkXG4gICAgY29uc3QgdXBkYXRlTm90ZUxhbWJkYSA9IG5ldyBOb2RlanNGdW5jdGlvbih0aGlzLCAnVXBkYXRlTm90ZUxhbWJkYScsIHtcbiAgICAgIGZ1bmN0aW9uTmFtZTogYCR7cHJlZml4fS11cGRhdGUtbm90ZWAsXG4gICAgICBydW50aW1lOiBsYW1iZGEuUnVudGltZS5OT0RFSlNfMThfWCxcbiAgICAgIGVudHJ5OiBwYXRoLmpvaW4oX19kaXJuYW1lLCAnLi4vbGFtYmRhL25vdGVzL3VwZGF0ZS9pbmRleC5qcycpLFxuICAgICAgaGFuZGxlcjogJ2hhbmRsZXInLFxuICAgICAgZW52aXJvbm1lbnQ6IGxhbWJkYUVudixcbiAgICAgIHRpbWVvdXQ6IGNkay5EdXJhdGlvbi5zZWNvbmRzKDMwKSxcbiAgICAgIG1lbW9yeVNpemU6IDI1NixcbiAgICAgIGJ1bmRsaW5nOiBidW5kbGluZ09wdGlvbnMsXG4gICAgfSk7XG5cbiAgICAvLyBQT1NUIC9ub3Rlcy9nZW5lcmF0ZSAtIEdlbmVyYXRlIHNhbXBsZSBwYXRpZW50IG5vdGUgZm9yIHRlc3RpbmdcbiAgICBjb25zdCBnZW5lcmF0ZU5vdGVMYW1iZGEgPSBuZXcgTm9kZWpzRnVuY3Rpb24odGhpcywgJ0dlbmVyYXRlTm90ZUxhbWJkYScsIHtcbiAgICAgIGZ1bmN0aW9uTmFtZTogYCR7cHJlZml4fS1nZW5lcmF0ZS1ub3RlYCxcbiAgICAgIHJ1bnRpbWU6IGxhbWJkYS5SdW50aW1lLk5PREVKU18xOF9YLFxuICAgICAgZW50cnk6IHBhdGguam9pbihfX2Rpcm5hbWUsICcuLi9sYW1iZGEvbm90ZXMvZ2VuZXJhdGUvaW5kZXguanMnKSxcbiAgICAgIGhhbmRsZXI6ICdoYW5kbGVyJyxcbiAgICAgIGVudmlyb25tZW50OiBsYW1iZGFFbnYsXG4gICAgICB0aW1lb3V0OiBjZGsuRHVyYXRpb24uc2Vjb25kcygzMCksXG4gICAgICBtZW1vcnlTaXplOiAyNTYsXG4gICAgICBidW5kbGluZzogYnVuZGxpbmdPcHRpb25zLFxuICAgIH0pO1xuXG4gICAgLy8gPT09PT09PT09PT09PT09PT09PT0gR3JhbnQgUGVybWlzc2lvbnMgPT09PT09PT09PT09PT09PT09PT1cblxuICAgIC8vIER5bmFtb0RCIHBlcm1pc3Npb25zXG4gICAgcGF0aWVudE1hc3RlclRhYmxlLmdyYW50UmVhZERhdGEobGlzdFBhdGllbnRzTGFtYmRhKTtcbiAgICBwYXRpZW50TWFzdGVyVGFibGUuZ3JhbnRSZWFkRGF0YShnZXRQYXRpZW50TGFtYmRhKTtcbiAgICBwYXRpZW50TWFzdGVyVGFibGUuZ3JhbnRSZWFkRGF0YShnZW5lcmF0ZVJlcG9ydExhbWJkYSk7XG4gICAgcGF0aWVudE1hc3RlclRhYmxlLmdyYW50UmVhZFdyaXRlRGF0YShzZWVkTGFtYmRhKTtcblxuICAgIHBhdGllbnRSZXN1bHRzVGFibGUuZ3JhbnRSZWFkV3JpdGVEYXRhKGdlbmVyYXRlUmVwb3J0TGFtYmRhKTtcbiAgICBwYXRpZW50UmVzdWx0c1RhYmxlLmdyYW50UmVhZERhdGEoZ2V0UmVwb3J0c0xhbWJkYSk7XG4gICAgcGF0aWVudFJlc3VsdHNUYWJsZS5ncmFudFJlYWREYXRhKGdldFBlbmRpbmdSZXBvcnRzTGFtYmRhKTtcbiAgICBwYXRpZW50UmVzdWx0c1RhYmxlLmdyYW50UmVhZFdyaXRlRGF0YSh1cGRhdGVSZXBvcnRMYW1iZGEpO1xuXG4gICAgLy8gUzMgcGVybWlzc2lvbnMgLSBSZXBvcnRzIGJ1Y2tldFxuICAgIHJlcG9ydHNCdWNrZXQuZ3JhbnRSZWFkV3JpdGUoZ2VuZXJhdGVSZXBvcnRMYW1iZGEpO1xuICAgIHJlcG9ydHNCdWNrZXQuZ3JhbnRSZWFkKGdldFJlcG9ydHNMYW1iZGEpO1xuICAgIHJlcG9ydHNCdWNrZXQuZ3JhbnRSZWFkKGdldFBlbmRpbmdSZXBvcnRzTGFtYmRhKTtcblxuICAgIC8vIFMzIHBlcm1pc3Npb25zIC0gTWVkaWNhbCBpbWFnZXMgYnVja2V0XG4gICAgbWVkaWNhbEltYWdlc0J1Y2tldC5ncmFudFJlYWQoZ2VuZXJhdGVSZXBvcnRMYW1iZGEpO1xuICAgIG1lZGljYWxJbWFnZXNCdWNrZXQuZ3JhbnRSZWFkV3JpdGUoc2VlZEltYWdlc0xhbWJkYSk7XG5cbiAgICAvLyBQYXRpZW50IE5vdGVzIHBlcm1pc3Npb25zXG4gICAgcGF0aWVudE5vdGVzVGFibGUuZ3JhbnRSZWFkV3JpdGVEYXRhKHJlY2VpdmVOb3RlTGFtYmRhKTtcbiAgICBwYXRpZW50Tm90ZXNUYWJsZS5ncmFudFJlYWREYXRhKGdldFBlbmRpbmdOb3Rlc0xhbWJkYSk7XG4gICAgcGF0aWVudE5vdGVzVGFibGUuZ3JhbnRSZWFkV3JpdGVEYXRhKHVwZGF0ZU5vdGVMYW1iZGEpO1xuICAgIHBhdGllbnROb3Rlc1RhYmxlLmdyYW50UmVhZFdyaXRlRGF0YShnZW5lcmF0ZU5vdGVMYW1iZGEpO1xuICAgIHBhdGllbnRNYXN0ZXJUYWJsZS5ncmFudFJlYWREYXRhKHJlY2VpdmVOb3RlTGFtYmRhKTsgLy8gRm9yIHBob25lIG51bWJlciBsb29rdXBcbiAgICBwYXRpZW50TWFzdGVyVGFibGUuZ3JhbnRSZWFkRGF0YShnZW5lcmF0ZU5vdGVMYW1iZGEpOyAvLyBGb3IgcmFuZG9tIHBhdGllbnQgc2VsZWN0aW9uXG5cbiAgICAvLyA9PT09PT09PT09PT09PT09PT09PSBBUEkgR2F0ZXdheSA9PT09PT09PT09PT09PT09PT09PVxuICAgIGNvbnN0IGFwaSA9IG5ldyBhcGlnYXRld2F5LlJlc3RBcGkodGhpcywgJ01lZGljYWxSZXBvcnRzQXBpJywge1xuICAgICAgcmVzdEFwaU5hbWU6IGAke3ByZWZpeH0tYXBpYCxcbiAgICAgIGRlc2NyaXB0aW9uOiAnTWVkaWNhbCBSZXBvcnRzIE1vY2sgU2VydmljZSBBUEknLFxuICAgICAgZGVmYXVsdENvcnNQcmVmbGlnaHRPcHRpb25zOiB7XG4gICAgICAgIGFsbG93T3JpZ2luczogYXBpZ2F0ZXdheS5Db3JzLkFMTF9PUklHSU5TLFxuICAgICAgICBhbGxvd01ldGhvZHM6IGFwaWdhdGV3YXkuQ29ycy5BTExfTUVUSE9EUyxcbiAgICAgIH0sXG4gICAgfSk7XG5cbiAgICAvLyAvcGF0aWVudHMgcmVzb3VyY2VcbiAgICBjb25zdCBwYXRpZW50c1Jlc291cmNlID0gYXBpLnJvb3QuYWRkUmVzb3VyY2UoJ3BhdGllbnRzJyk7XG4gICAgcGF0aWVudHNSZXNvdXJjZS5hZGRNZXRob2QoJ0dFVCcsIG5ldyBhcGlnYXRld2F5LkxhbWJkYUludGVncmF0aW9uKGxpc3RQYXRpZW50c0xhbWJkYSkpO1xuXG4gICAgLy8gL3BhdGllbnRzL3tpZH0gcmVzb3VyY2VcbiAgICBjb25zdCBwYXRpZW50QnlJZFJlc291cmNlID0gcGF0aWVudHNSZXNvdXJjZS5hZGRSZXNvdXJjZSgne2lkfScpO1xuICAgIHBhdGllbnRCeUlkUmVzb3VyY2UuYWRkTWV0aG9kKCdHRVQnLCBuZXcgYXBpZ2F0ZXdheS5MYW1iZGFJbnRlZ3JhdGlvbihnZXRQYXRpZW50TGFtYmRhKSk7XG5cbiAgICAvLyAvcmVwb3J0cyByZXNvdXJjZVxuICAgIGNvbnN0IHJlcG9ydHNSZXNvdXJjZSA9IGFwaS5yb290LmFkZFJlc291cmNlKCdyZXBvcnRzJyk7XG5cbiAgICAvLyAvcmVwb3J0cy9nZW5lcmF0ZSByZXNvdXJjZVxuICAgIGNvbnN0IGdlbmVyYXRlUmVzb3VyY2UgPSByZXBvcnRzUmVzb3VyY2UuYWRkUmVzb3VyY2UoJ2dlbmVyYXRlJyk7XG4gICAgZ2VuZXJhdGVSZXNvdXJjZS5hZGRNZXRob2QoJ1BPU1QnLCBuZXcgYXBpZ2F0ZXdheS5MYW1iZGFJbnRlZ3JhdGlvbihnZW5lcmF0ZVJlcG9ydExhbWJkYSkpO1xuXG4gICAgLy8gL3JlcG9ydHMvZ2VuZXJhdGUve3BhdGllbnRfaWR9IHJlc291cmNlXG4gICAgY29uc3QgZ2VuZXJhdGVCeVBhdGllbnRSZXNvdXJjZSA9IGdlbmVyYXRlUmVzb3VyY2UuYWRkUmVzb3VyY2UoJ3twYXRpZW50X2lkfScpO1xuICAgIGdlbmVyYXRlQnlQYXRpZW50UmVzb3VyY2UuYWRkTWV0aG9kKCdQT1NUJywgbmV3IGFwaWdhdGV3YXkuTGFtYmRhSW50ZWdyYXRpb24oZ2VuZXJhdGVSZXBvcnRMYW1iZGEpKTtcblxuICAgIC8vIC9yZXBvcnRzL3BlbmRpbmcgcmVzb3VyY2VcbiAgICBjb25zdCBwZW5kaW5nUmVzb3VyY2UgPSByZXBvcnRzUmVzb3VyY2UuYWRkUmVzb3VyY2UoJ3BlbmRpbmcnKTtcbiAgICBwZW5kaW5nUmVzb3VyY2UuYWRkTWV0aG9kKCdHRVQnLCBuZXcgYXBpZ2F0ZXdheS5MYW1iZGFJbnRlZ3JhdGlvbihnZXRQZW5kaW5nUmVwb3J0c0xhbWJkYSkpO1xuXG4gICAgLy8gL3JlcG9ydHMve3BhdGllbnRfaWR9IHJlc291cmNlIChmb3IgZ2V0dGluZyByZXBvcnRzIGJ5IHBhdGllbnQpXG4gICAgY29uc3QgcmVwb3J0c0J5UGF0aWVudFJlc291cmNlID0gcmVwb3J0c1Jlc291cmNlLmFkZFJlc291cmNlKCd7cGF0aWVudF9pZH0nKTtcbiAgICByZXBvcnRzQnlQYXRpZW50UmVzb3VyY2UuYWRkTWV0aG9kKCdHRVQnLCBuZXcgYXBpZ2F0ZXdheS5MYW1iZGFJbnRlZ3JhdGlvbihnZXRSZXBvcnRzTGFtYmRhKSk7XG5cbiAgICAvLyAvcmVwb3J0cy91cGRhdGUve3JlcG9ydF9pZH0gcmVzb3VyY2VcbiAgICBjb25zdCB1cGRhdGVSZXNvdXJjZSA9IHJlcG9ydHNSZXNvdXJjZS5hZGRSZXNvdXJjZSgndXBkYXRlJyk7XG4gICAgY29uc3QgdXBkYXRlQnlJZFJlc291cmNlID0gdXBkYXRlUmVzb3VyY2UuYWRkUmVzb3VyY2UoJ3tyZXBvcnRfaWR9Jyk7XG4gICAgdXBkYXRlQnlJZFJlc291cmNlLmFkZE1ldGhvZCgnUEFUQ0gnLCBuZXcgYXBpZ2F0ZXdheS5MYW1iZGFJbnRlZ3JhdGlvbih1cGRhdGVSZXBvcnRMYW1iZGEpKTtcblxuICAgIC8vIC9zZWVkIHJlc291cmNlIChmb3IgcG9wdWxhdGluZyBpbml0aWFsIGRhdGEpXG4gICAgY29uc3Qgc2VlZFJlc291cmNlID0gYXBpLnJvb3QuYWRkUmVzb3VyY2UoJ3NlZWQnKTtcbiAgICBzZWVkUmVzb3VyY2UuYWRkTWV0aG9kKCdQT1NUJywgbmV3IGFwaWdhdGV3YXkuTGFtYmRhSW50ZWdyYXRpb24oc2VlZExhbWJkYSkpO1xuXG4gICAgLy8gL3NlZWQvaW1hZ2VzIHJlc291cmNlIChmb3IgcG9wdWxhdGluZyBtZWRpY2FsIGltYWdlcyBmcm9tIE5JSCBkYXRhc2V0KVxuICAgIGNvbnN0IHNlZWRJbWFnZXNSZXNvdXJjZSA9IHNlZWRSZXNvdXJjZS5hZGRSZXNvdXJjZSgnaW1hZ2VzJyk7XG4gICAgc2VlZEltYWdlc1Jlc291cmNlLmFkZE1ldGhvZCgnUE9TVCcsIG5ldyBhcGlnYXRld2F5LkxhbWJkYUludGVncmF0aW9uKHNlZWRJbWFnZXNMYW1iZGEpKTtcblxuICAgIC8vID09PT09PT09PT09PT09PT09PT09IFBhdGllbnQgTm90ZXMgRW5kcG9pbnRzID09PT09PT09PT09PT09PT09PT09XG5cbiAgICAvLyAvbm90ZXMgcmVzb3VyY2VcbiAgICBjb25zdCBub3Rlc1Jlc291cmNlID0gYXBpLnJvb3QuYWRkUmVzb3VyY2UoJ25vdGVzJyk7XG5cbiAgICAvLyBQT1NUIC9ub3RlcyAtIFJlY2VpdmUgcGF0aWVudCBub3RlIGZyb20gVHdpbGlvIHdlYmhvb2tcbiAgICBub3Rlc1Jlc291cmNlLmFkZE1ldGhvZCgnUE9TVCcsIG5ldyBhcGlnYXRld2F5LkxhbWJkYUludGVncmF0aW9uKHJlY2VpdmVOb3RlTGFtYmRhKSk7XG5cbiAgICAvLyAvbm90ZXMvcGVuZGluZyAtIEdldCB1bnByb2Nlc3NlZCBub3RlcyBmb3IgQUkgdG8gcHJvY2Vzc1xuICAgIGNvbnN0IHBlbmRpbmdOb3Rlc1Jlc291cmNlID0gbm90ZXNSZXNvdXJjZS5hZGRSZXNvdXJjZSgncGVuZGluZycpO1xuICAgIHBlbmRpbmdOb3Rlc1Jlc291cmNlLmFkZE1ldGhvZCgnR0VUJywgbmV3IGFwaWdhdGV3YXkuTGFtYmRhSW50ZWdyYXRpb24oZ2V0UGVuZGluZ05vdGVzTGFtYmRhKSk7XG5cbiAgICAvLyAvbm90ZXMvdXBkYXRlL3tub3RlX2lkfSAtIE1hcmsgbm90ZSBhcyBwcm9jZXNzZWRcbiAgICBjb25zdCB1cGRhdGVOb3RlUmVzb3VyY2UgPSBub3Rlc1Jlc291cmNlLmFkZFJlc291cmNlKCd1cGRhdGUnKTtcbiAgICBjb25zdCB1cGRhdGVOb3RlQnlJZFJlc291cmNlID0gdXBkYXRlTm90ZVJlc291cmNlLmFkZFJlc291cmNlKCd7bm90ZV9pZH0nKTtcbiAgICB1cGRhdGVOb3RlQnlJZFJlc291cmNlLmFkZE1ldGhvZCgnUEFUQ0gnLCBuZXcgYXBpZ2F0ZXdheS5MYW1iZGFJbnRlZ3JhdGlvbih1cGRhdGVOb3RlTGFtYmRhKSk7XG5cbiAgICAvLyAvbm90ZXMvZ2VuZXJhdGUgLSBHZW5lcmF0ZSBzYW1wbGUgcGF0aWVudCBub3RlIGZvciB0ZXN0aW5nXG4gICAgY29uc3QgZ2VuZXJhdGVOb3RlUmVzb3VyY2UgPSBub3Rlc1Jlc291cmNlLmFkZFJlc291cmNlKCdnZW5lcmF0ZScpO1xuICAgIGdlbmVyYXRlTm90ZVJlc291cmNlLmFkZE1ldGhvZCgnUE9TVCcsIG5ldyBhcGlnYXRld2F5LkxhbWJkYUludGVncmF0aW9uKGdlbmVyYXRlTm90ZUxhbWJkYSkpO1xuXG4gICAgLy8gL25vdGVzL2dlbmVyYXRlL3twYXRpZW50X2lkfSAtIEdlbmVyYXRlIG5vdGUgZm9yIHNwZWNpZmljIHBhdGllbnRcbiAgICBjb25zdCBnZW5lcmF0ZU5vdGVCeVBhdGllbnRSZXNvdXJjZSA9IGdlbmVyYXRlTm90ZVJlc291cmNlLmFkZFJlc291cmNlKCd7cGF0aWVudF9pZH0nKTtcbiAgICBnZW5lcmF0ZU5vdGVCeVBhdGllbnRSZXNvdXJjZS5hZGRNZXRob2QoJ1BPU1QnLCBuZXcgYXBpZ2F0ZXdheS5MYW1iZGFJbnRlZ3JhdGlvbihnZW5lcmF0ZU5vdGVMYW1iZGEpKTtcblxuICAgIC8vID09PT09PT09PT09PT09PT09PT09IE91dHB1dHMgPT09PT09PT09PT09PT09PT09PT1cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnQXBpVXJsJywge1xuICAgICAgdmFsdWU6IGFwaS51cmwsXG4gICAgICBkZXNjcmlwdGlvbjogJ0FQSSBHYXRld2F5IFVSTCcsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnQnVja2V0TmFtZScsIHtcbiAgICAgIHZhbHVlOiByZXBvcnRzQnVja2V0LmJ1Y2tldE5hbWUsXG4gICAgICBkZXNjcmlwdGlvbjogJ1MzIEJ1Y2tldCBmb3IgcmVwb3J0cycsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnTWVkaWNhbEltYWdlc0J1Y2tldE5hbWUnLCB7XG4gICAgICB2YWx1ZTogbWVkaWNhbEltYWdlc0J1Y2tldC5idWNrZXROYW1lLFxuICAgICAgZGVzY3JpcHRpb246ICdTMyBCdWNrZXQgZm9yIHJlYWwgbWVkaWNhbCBpbWFnZXMgKE5JSCBDaGVzdFgtcmF5MTQsIExJREMsIGV0Yy4pJyxcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdQYXRpZW50TWFzdGVyVGFibGVOYW1lJywge1xuICAgICAgdmFsdWU6IHBhdGllbnRNYXN0ZXJUYWJsZS50YWJsZU5hbWUsXG4gICAgICBkZXNjcmlwdGlvbjogJ1BhdGllbnQgTWFzdGVyIER5bmFtb0RCIFRhYmxlJyxcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdQYXRpZW50UmVzdWx0c1RhYmxlTmFtZScsIHtcbiAgICAgIHZhbHVlOiBwYXRpZW50UmVzdWx0c1RhYmxlLnRhYmxlTmFtZSxcbiAgICAgIGRlc2NyaXB0aW9uOiAnUGF0aWVudCBSZXN1bHRzIER5bmFtb0RCIFRhYmxlJyxcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdQYXRpZW50Tm90ZXNUYWJsZU5hbWUnLCB7XG4gICAgICB2YWx1ZTogcGF0aWVudE5vdGVzVGFibGUudGFibGVOYW1lLFxuICAgICAgZGVzY3JpcHRpb246ICdQYXRpZW50IE5vdGVzIER5bmFtb0RCIFRhYmxlIChTTVMgbWVzc2FnZXMgZnJvbSBwYXRpZW50cyknLFxuICAgIH0pO1xuICB9XG59XG4iXX0=
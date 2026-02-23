#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { MedicalReportsServiceStack } from '../lib/medical_reports-service-stack';

const app = new cdk.App();
new MedicalReportsServiceStack(app, 'MedicalReportsServiceStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: 'us-east-1'
  },
  description: 'MedGemma Challenge - Medical Reports Mock Service'
});
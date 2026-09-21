#!/usr/bin/env node
import * as cdk from '@aws-cdk/core';
import { UIResourceStack } from '../lib/ui-resource-stack';
import { config } from '../bin/config';

class UIResource extends cdk.Stack {
  constructor(parent: cdk.App, name: string, props: cdk.StackProps) {
    super(parent, name, props);

    new UIResourceStack(this, 'UIResourceStack', {
      domainName: config.UI_DOMAIN,
      siteSubDomain: config.UI_SUBDOMAIN,
    });
  }
}

const app = new cdk.App();

new UIResource(app, 'UIResource', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  },
});

app.synth();

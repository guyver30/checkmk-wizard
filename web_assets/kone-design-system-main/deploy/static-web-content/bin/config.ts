import * as envalid from 'envalid';

export const config = envalid.cleanEnv(process.env, {
  UI_DOMAIN: envalid.str(),
  UI_SUBDOMAIN: envalid.str(),
});

export const isProduction = config.ENVIRONMENT_NAME === 'prod';

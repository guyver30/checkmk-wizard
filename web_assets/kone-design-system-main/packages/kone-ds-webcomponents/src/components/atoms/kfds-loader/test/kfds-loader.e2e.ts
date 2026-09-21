import { newE2EPage } from '@stencil/core/testing';

describe('kfds-loader', () => {
  it('renders', async () => {
    const page = await newE2EPage();
    await page.setContent('<kfds-loader></kfds-loader>');

    const element = await page.find('kfds-loader');
    expect(element).toHaveClass('hydrated');
  });
});

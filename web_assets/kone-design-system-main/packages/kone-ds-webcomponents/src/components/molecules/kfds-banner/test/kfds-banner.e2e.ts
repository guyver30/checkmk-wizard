import { newE2EPage } from '@stencil/core/testing';

describe('kfds-banner', () => {
  it('renders', async () => {
    const page = await newE2EPage();
    await page.setContent('<kfds-banner></kfds-banner>');

    const element = await page.find('kfds-banner');
    expect(element).toHaveClass('hydrated');
  });
});

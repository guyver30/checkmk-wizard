import { newE2EPage } from '@stencil/core/testing';

describe('kfds-message', () => {
  it('renders', async () => {
    const page = await newE2EPage();
    await page.setContent('<kfds-message></kfds-message>');

    const element = await page.find('kfds-message');
    expect(element).toHaveClass('hydrated');
  });
});

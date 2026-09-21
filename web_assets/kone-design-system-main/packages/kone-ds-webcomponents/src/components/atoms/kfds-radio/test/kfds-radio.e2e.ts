import { newE2EPage } from '@stencil/core/testing';

describe('kfds-radio', () => {
  it('renders', async () => {
    const page = await newE2EPage();
    await page.setContent('<kfds-radio></kfds-radio>');

    const element = await page.find('kfds-radio');
    expect(element).toHaveClass('hydrated');
  });
});

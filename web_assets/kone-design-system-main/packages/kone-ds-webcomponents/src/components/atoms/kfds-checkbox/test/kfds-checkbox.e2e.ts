import { newE2EPage } from '@stencil/core/testing';

describe('kfds-checkbox', () => {
  it('renders', async () => {
    const page = await newE2EPage();
    await page.setContent('<kfds-checkbox></kfds-checkbox>');

    const element = await page.find('kfds-checkbox');
    expect(element).toHaveClass('hydrated');
  });
});

import { newE2EPage } from '@stencil/core/testing';

describe('kfds-modal', () => {
  it('renders', async () => {
    const page = await newE2EPage();
    await page.setContent('<kfds-modal></kfds-modal>');

    const element = await page.find('kfds-modal');
    expect(element).toHaveClass('hydrated');
  });
});

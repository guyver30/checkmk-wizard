import { newE2EPage } from '@stencil/core/testing';

describe('kfds-tooltip', () => {
  it('renders', async () => {
    const page = await newE2EPage();
    await page.setContent('<kfds-tooltip></kfds-tooltip>');

    const element = await page.find('kfds-tooltip');
    expect(element).toHaveClass('hydrated');
  });
});

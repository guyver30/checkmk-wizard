import { newE2EPage } from '@stencil/core/testing';

describe('kfds-button', () => {
  it('renders', async () => {
    const page = await newE2EPage();
    await page.setContent('<kfds-button></kfds-button>');

    const element = await page.find('kfds-button');
    expect(element).toHaveClass('hydrated');
  });
});

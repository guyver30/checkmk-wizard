import { newE2EPage } from '@stencil/core/testing';

describe('kfds-input', () => {
  it('renders', async () => {
    const page = await newE2EPage();
    await page.setContent('<kfds-input></kfds-input>');

    const element = await page.find('kfds-input');
    expect(element).toHaveClass('hydrated');
  });
});

import { newE2EPage } from '@stencil/core/testing';

describe('kfds-hyperlink', () => {
  it('renders', async () => {
    const page = await newE2EPage();
    await page.setContent('<kfds-hyperlink></kfds-hyperlink>');

    const element = await page.find('kfds-hyperlink');
    expect(element).toHaveClass('hydrated');
  });
});

import { newE2EPage } from '@stencil/core/testing';

describe('kfds-snackbar', () => {
  it('renders', async () => {
    const page = await newE2EPage();
    await page.setContent('<kfds-snackbar></kfds-snackbar>');

    const element = await page.find('kfds-snackbar');
    expect(element).toHaveClass('hydrated');
  });
});

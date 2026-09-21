import { newSpecPage } from '@stencil/core/testing';
import { KfdsSnackbar } from '../kfds-snackbar';

describe('kfds-snackbar', () => {
  it('renders', async () => {
    const page = await newSpecPage({
      components: [KfdsSnackbar],
      html: `<kfds-snackbar></kfds-snackbar>`,
    });
    expect(page.root).toEqualHtml(`
      <kfds-snackbar>
        <mock:shadow-root>
          <slot></slot>
        </mock:shadow-root>
      </kfds-snackbar>
    `);
  });
});

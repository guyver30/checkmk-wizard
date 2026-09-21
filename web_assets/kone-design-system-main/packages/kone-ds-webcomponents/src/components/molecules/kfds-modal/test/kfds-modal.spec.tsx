import { newSpecPage } from '@stencil/core/testing';
import { KfdsModal } from '../kfds-modal';

describe('kfds-modal', () => {
  it('renders', async () => {
    const page = await newSpecPage({
      components: [KfdsModal],
      html: `<kfds-modal></kfds-modal>`,
    });
    expect(page.root).toEqualHtml(`
      <kfds-modal>
        <mock:shadow-root>
          <slot></slot>
        </mock:shadow-root>
      </kfds-modal>
    `);
  });
});

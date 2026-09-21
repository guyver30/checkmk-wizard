import { newSpecPage } from '@stencil/core/testing';
import { KfdsBreadcrumb } from '../kfds-breadcrumb';

describe('kfds-breadcrumb', () => {
  it('renders', async () => {
    const page = await newSpecPage({
      components: [KfdsBreadcrumb],
      html: `<kfds-breadcrumb></kfds-breadcrumb>`,
    });
    expect(page.root).toEqualHtml(`
      <kfds-breadcrumb>
        <mock:shadow-root>
          <slot></slot>
        </mock:shadow-root>
      </kfds-breadcrumb>
    `);
  });
});

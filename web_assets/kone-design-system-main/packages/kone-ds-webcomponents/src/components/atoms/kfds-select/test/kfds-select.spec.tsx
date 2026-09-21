import { newSpecPage } from '@stencil/core/testing';
import { KfdsSelect } from '../kfds-select';

describe('kfds-select', () => {
  it('renders', async () => {
    const page = await newSpecPage({
      components: [KfdsSelect],
      html: `<kfds-select></kfds-select>`,
    });
    expect(page.root).toEqualHtml(`
      <kfds-select>
        <mock:shadow-root>
          <slot></slot>
        </mock:shadow-root>
      </kfds-select>
    `);
  });
});

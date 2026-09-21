import { NgModule } from '@angular/core';
import { KoneDsWebcomponentsAngularComponent } from './kone-ds-webcomponents-angular.component';
import { DIRECTIVES } from './stencil-generated';

@NgModule({
  declarations: [
    KoneDsWebcomponentsAngularComponent,
    ...DIRECTIVES
  ],
  imports: [
  ],
  exports: [
    KoneDsWebcomponentsAngularComponent,
    ...DIRECTIVES
  ]
})
export class KoneDsWebcomponentsAngularModule { }

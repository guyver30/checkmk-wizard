import { ComponentFixture, TestBed } from '@angular/core/testing';

import { KoneDsWebcomponentsAngularComponent } from './kone-ds-webcomponents-angular.component';

describe('KoneDsWebcomponentsAngularComponent', () => {
  let component: KoneDsWebcomponentsAngularComponent;
  let fixture: ComponentFixture<KoneDsWebcomponentsAngularComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      declarations: [ KoneDsWebcomponentsAngularComponent ]
    })
    .compileComponents();

    fixture = TestBed.createComponent(KoneDsWebcomponentsAngularComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});

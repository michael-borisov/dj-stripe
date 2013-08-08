from __future__ import unicode_literals
import json

from django.core.urlresolvers import reverse_lazy
from django.http import HttpResponse
from django.shortcuts import render
from django.views.generic import DetailView
from django.views.generic import FormView
from django.views.generic import TemplateView
from django.views.generic import View

from braces.views import CsrfExemptMixin
from braces.views import LoginRequiredMixin
from braces.views import SelectRelatedMixin
import stripe

from .forms import PlanForm
from .models import CurrentSubscription
from .models import Customer
from .models import Event
from .models import EventProcessingException
from .settings import PLAN_CHOICES
from .settings import PLAN_LIST
from .settings import PY3
from .sync import sync_customer
from .viewmixins import PaymentsContextMixin

# This is here as a utility. Might move it out.
from .viewmixins import SubscriptionPaymentRequiredMixin


class SubscribeFormView(
        LoginRequiredMixin,
        PaymentsContextMixin,
        FormView):
    # TODO - needs tests

    form_class = PlanForm
    template_name = "djstripe/subscribe_form.html"
    success_url = reverse_lazy("djstripe:history")

    def get_context_data(self, *args, **kwargs):
        context = super(SubscribeFormView, self).get_context_data(**kwargs)
        context['is_plans_plural'] = bool(len(PLAN_CHOICES) > 1)
        context['customer'], created = Customer.get_or_create(self.request.user)
        return context

    def post(self, request, *args, **kwargs):
        """
        Handles POST requests, instantiating a form instance with the passed
        POST variables and then checked for validity.
        """
        form_class = self.get_form_class()
        form = self.get_form(form_class)
        if form.is_valid():
            try:
                customer, created = Customer.get_or_create(self.request.user)
                customer.update_card(self.request.POST.get("stripe_token"))
                customer.subscribe(form.cleaned_data["plan"])
            except stripe.StripeError as e:
                # add form error here
                self.error = e.args[0]
                return self.form_invalid(form)
            # redirect to confirmation page
            return self.form_valid(form)
        else:
            return self.form_invalid(form)


class ChangeCardView(LoginRequiredMixin, PaymentsContextMixin, TemplateView):
    # TODO - needs tests
    template_name = "djstripe/change_card.html"


class CancelView(LoginRequiredMixin, PaymentsContextMixin, TemplateView):
    # TODO - needs tests
    template_name = "djstripe/cancel.html"


class WebHook(CsrfExemptMixin, View):

    def post(self, request, *args, **kwargs):
        if PY3:
            # Handles Python 3 conversion of bytes to str
            body = request.body.decode(encoding="UTF-8")
        else:
            # Handles Python 2
            body = request.body
        data = json.loads(body)
        if Event.objects.filter(stripe_id=data["id"]).exists():
            EventProcessingException.objects.create(
                data=data,
                message="Duplicate event record",
                traceback=""
            )
        else:
            event = Event.objects.create(
                stripe_id=data["id"],
                kind=data["type"],
                livemode=data["livemode"],
                webhook_message=data
            )
            event.validate()
            event.process()
        return HttpResponse()


class HistoryView(LoginRequiredMixin, SelectRelatedMixin, DetailView):
    # TODO - needs tests
    template_name = "djstripe/history.html"
    model = Customer
    select_related = ["invoice"]

    def get_object(self):
        customer, created = Customer.get_or_create(self.request.user)
        return customer


class SyncHistoryView(CsrfExemptMixin, LoginRequiredMixin, View):
    # TODO - needs tests
    def post(self, request, *args, **kwargs):
        return render(
            request,
            "djstripe/includes/_history_table.html",
            {"customer": sync_customer(request.user)}
        )


class AccountView(LoginRequiredMixin, SelectRelatedMixin, TemplateView):
    # TODO - needs tests
    template_name = "djstripe/account.html"

    def get_context_data(self, *args, **kwargs):
        context = super(AccountView, self).get_context_data(**kwargs)
        customer, created = Customer.get_or_create(self.request.user)
        context['customer'] = customer
        try:
            context['subscription'] = customer.current_subscription
        except CurrentSubscription.DoesNotExist:
            context['subscription'] = None
        context['plans'] = PLAN_LIST
        return context

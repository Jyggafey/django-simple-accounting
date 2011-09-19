from django.conf import settings 
from django.db import models
from django.db.models import get_model
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import ugettext_lazy as _
from django.core.exceptions import ValidationError, ImproperlyConfigured

from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import generic

from accounting.fields import CurrencyField

from datetime import datetime


class Subject(models.Model):
    """ 
    A wrapper model intended to provide an uniform interface to 'subjective models'. 
    
    A 'subjective model' is defined as one whose instances can play some specific roles
    in a financial context, such as owning an account, being charged for an invoice, and so on.
    
    This model use Django's ``ContentType`` framework in order to allow a model 
    to define foreign-key or many-to-many relationships with a generic subjective model.
    
    For example, if the ``bar`` field in the ``Foo`` model class should be able to relate to 
    several different subjective models (as for example ``Person``, ``Company``, etc.), 
    just declare it as follows:
    
    class Foo(models.Model):
        # ...
        bar = models.ForeignKey(Subject)
        # ...    
    """
    content_type = models.ForeignKey(ContentType)
    object_id = models.PositiveIntegerField()
    instance = generic.GenericForeignKey(ct_field="content_type", fk_field="object_id")
    
    def __unicode__(self):
        return " %(ct)s %(instance)s" % {'ct':str(self.content_type).capitalize(), 'instance':self.instance}


try:
    subjective_models = [get_model(*model_str.split('.')) for model_str in settings.SUBJECTIVE_MODELS]
except TypeError:
    err_msg = "The current 'SUBJECTIVE_MODELS' setting is invalid: %s \n It must contain only labels for existing models"\
        % settings.SUBJECTIVE_MODELS
    raise ImproperlyConfigured(err_msg)

# when a new instance of a subjective model is created, 
# add a corresponding ``Subject`` instance pointing to it
# TODO: deal with subjective models's instances added via fixtures
@receiver(post_save)
def subjectify(sender, instance, created, **kwargs):
    if sender in subjective_models and created:
        ct = ContentType.objects.get_for_model(sender)
        Subject.objects.create(content_type=ct, object_id=instance.pk)     
    

class Account(models.Model):
    """
    An account within a double-entry accounting system.
    
    From an abstract point of view, there are two general kind of accounts:
    1) those which are stocks of money, either positive (assets) or negative (liabilities)
    2) those which represent entry-points in the system (e.g incomes) or exit-points (e.g. expenses) from it   
    
    As a data stucture, an account is just a collection of transactions
    between either two accounts in the system  or an account in the system
    and one outside it. 
    
    Accounts are hierarchically organized in a tree-like structure, 
    and are owned by somebody.  
    
    An account can be merely a placeholder (just a container of subaccounts, no transactions).  
    """
    
    parent = models.ForeignKey('Account', null=True, blank=True)
    name = models.CharField(max_length=128)
    kind = models.CharField(max_length=128, choices=settings.ACCOUNT_TYPES)
    placeholder = models.BooleanField(default=False)
    owner = models.ForeignKey(Subject)
    
    @property
    def balance(self):
        """
        The balance of this account (as a signed Decimal number).
        """
        # FIXME: implement caching !
        incoming_transactions = self.incoming_transaction_set.all()
        outgoing_transactions = self.outgoing_transaction_set.all()
        
        balance = 0
        for transaction in incoming_transactions:
            balance += transaction.net_amount 
        for transaction in outgoing_transactions:
            balance -= transaction.net_amount
        return balance
    
    @property
    def path(self):
        """
        The tree path needed to reach this account from the root of the account system,
        in the form 'root:account:subaccount:...' .
        """
        raise NotImplementedError 
    
    @property
    def is_root(self):
        """
        Return ``True`` if this account is a root one, ``False`` otherwise.
        """
        return not self.parent
    
    @property
    def root(self):
        """
        The root account for the account system this account belongs to.
        """
        # FIXME: implement caching !
        if self.is_root:
            return self
        else: 
            return self.parent.root
    
    @property
    def account_system_owner(self):
        """
        The subject owning the account system this account belongs to.
        """
        # FIXME: implement caching !
        if self.is_root:
            return self.owner
        else: 
            return self.parent.account_system_owner         
    
    def __unicode__(self):
        return _("Account %(path)s of the system owned by %(subject)s") % {'path':self.path, 'subject':self.root.owner}

class Transaction(models.Model):
    """
    A transaction within a double-entry accounting system.
    
    From an abstract point of view, a transaction is a just a money flow between two accounts, 
    of which at least one is internal to the system.     
    
    A transaction can etiher increase/decrease the amount of money globally contained within the system,
    or just represent a transfer between system stocks. 
    
    A transaction is characterized at least by:
    * a source account
    * a destination/target account
    * the amount of money transferred from/to both directions
    * the date when it happened
    * a reason for the transfer
    * who autorized the transaction 
    """

    # source account for the transaction
    source = models.ForeignKey(Account, related_name='outgoing_transaction_set')
    # target account for the transaction
    destination = models.ForeignKey(Account, related_name='incoming_transaction_set')
    # A transaction can have a plus- and minus- part, or both
    plus_amount = CurrencyField(blank=True, null=True)
    minus_amount = CurrencyField(blank=True, null=True)
    # given the transaction type, some fields can be auto-set (e.g. source/destination account)
    kind = models.CharField(max_length=128, choices=settings.TRANSACTION_TYPES)
    # when the transaction happened
    date = models.DateTimeField(default=datetime.now)
    # what the transaction represents
    description = models.CharField(max_length=512, help_text=_("Reason of the transaction"))
    # who triggered the transaction
    issuer = models.ForeignKey(Subject)     

    def __unicode__(self):
        return _("%(type)s issued by %(issuer)s at %(date)s") % {'type' : self.type, 'issuer' : self.issuer, 'date' : self.date}
    
    @property
    def net_amount(self):
        return self.plus_amount - self.minus_amount
    
    # model-level custom validation goes here
    def clean(self):
        if not (self.plus_amount or self.minus_amount):
            raise ValidationError(_("You must specify either a plus(+) or minus(-) amount for this transaction"))
        
    def save(self, *args, **kwargs):
        # perform model validation
        self.full_clean()
        super(Transaction, self).save(*args, **kwargs)
    
    
class Invoice(models.Model):
    """
    An invoice document issued by a subject against another subject.
    
    This model contains metadata useful for invoice management, embodying the actual document as a `FileField`. 
    
    Those metadata can be used to link invoices (particularly supplier ones) with GAS accounting management;    
    for example, when an invoice is payed, the system could automatically create a transaction reflecting this action.     
    """
    # who issued the invoice
    issuer = models.ForeignKey(Subject, related_name='issued_invoice_set')
    # who have to pay for the invoice
    recipient = models.ForeignKey(Subject, related_name='received_invoice_set')
    # invoice's amount (excluding taxes)
    net_amount = CurrencyField()
    # taxes due for the invoice (VAT,..)
    taxes = CurrencyField(blank=True, null=True)
    # when the invoice has been issued
    issue_date = models.DateTimeField()
    # when the invoice is due
    due_date = models.DateTimeField()
    # FIXME: implement a more granular storage pattern
    document = models.FileField(upload_to='/invoices')
    
    def __unicode__(self):
        return _("Invoice issued by %(issuer)s to %(recipient)s on date %(issue_date)s" % {'issuer' : self.issuer, 'recipient' : self.recipient, 'issue_date' : self.issue_date} )
    
    @property
    def total_amount(self):
        """Total amount for the invoice (including taxes)."""
        return self.net_amount + self.taxes  
    
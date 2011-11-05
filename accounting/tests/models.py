from django.db import models

from accounting.fields import CurrencyField
from accounting.models import AccountType, Account
from accounting.models import AccountingProxy, economic_subject
from accounting import types

## People
@economic_subject
class Person(models.Model):
    name = models.CharField(max_length=128)
    surname = models.CharField(max_length=128)
    
    @property
    def full_name(self):
        return self.name + self.surname
    
    def setup_accounting(self):
        self.subject.init_accounting_system()
        system = self.accounting_system
        # create a generic asset-type account (a sort of "virtual wallet")
        system.add_account(parent=system.root, name='wallet', kind=types.asset)  
    
    def save(self, *args, **kwargs):
        # run only at instance creation-time 
        if not self.pk:
            self.setup_accounting() 
        super(Person, self).save(*args, **kwargs)

    
## GASs
@economic_subject
class GAS(models.Model):
    name = models.CharField(max_length=128, unique=True)

    def setup_accounting(self):
        self.subject.init_accounting_system()
        system = self.accounting_system
        ## setup a base account hierarchy
        # GAS's cash       
        system.add_account(parent=system.root, name='cash', kind=types.asset) 
        # root for GAS members' accounts 
        system.add_account(parent=system.root, name='members', kind=types.asset, placeholder=True)
        # a placeholder for organizing transactions representing payments to suppliers
        system.add_account(parent_path='/expenses', name='suppliers', kind=types.expense, placeholder=True)
        # recharges made by GAS members to their own account
        system.add_account(parent_path='/incomes', name='recharges', kind=types.income)
        # membership fees
        system.add_account(parent_path='/incomes', name='fees', kind=types.income)
        
    def save(self, *args, **kwargs):
        # run only at instance creation-time 
        if not self.pk:
            self.setup_accounting() 
        super(GAS, self).save(*args, **kwargs)


class GASMember(models.Model):
    person = models.ForeignKey(Person)
    gas = models.ForeignKey(GAS)
    
    def setup_accounting(self):
        person_system = self.person.subject.accounting_system
        gas_system = self.gas.subject.accounting_system
        
        ## account creation
        ## Person-side
        try:
            base_account = person_system['/expenses/gas'] 
        except Account.DoesNotExist:
            person_system.add_account(parent_path='/expenses', name='gas', kind=types.expense, placeholder=True)
        # placeholder for payments made to the GAS
        person_system.add_account(parent=base_account, name=str(self.gas.name), kind=types.expense, placeholder=True)
        # recharges
        person_system.add_account(parent_path='/expenses/' + str(self.gas.name), name='recharges', kind=types.expense)
        # membership fees
        person_system.add_account(parent_path='/expenses/' + str(self.gas.name), name='fees', kind=types.expense)
        ## GAS-side   
        gas_system.add_account(parent_path='/members', name=str(self.person.full_name), kind=types.asset)
    
    def save(self, *args, **kwargs):
        # run only at instance creation-time 
        if not self.pk:
            self.setup_accounting() 
        super(GASMember, self).save(*args, **kwargs)
    
## Suppliers     
@economic_subject              
class Supplier(models.Model):
    name = models.CharField(max_length=128, unique=True)
    
    def setup_accounting(self):
        self.subject.init_accounting_system()
        system = self.accounting_system
        ## setup a base account hierarchy   
        # a generic asset-type account (a sort of "virtual wallet")        
        system.add_account(parent=system.root, name='wallet', kind=types.asset)  
        # a placeholder for organizing transactions representing GAS payments
        system.add_account(parent_path='/incomes', name='gas', kind=types.income, placeholder=True)
        
    def save(self, *args, **kwargs):
        # run only at instance creation-time 
        if not self.pk:
            self.setup_accounting() 
        super(Supplier, self).save(*args, **kwargs)


class Product(models.Model):
    name = models.CharField(max_length=128)
     

class SupplierStock(models.Model):
    supplier = models.ForeignKey(Supplier, related_name='stock_set')
    product = models.ForeignKey(Product, related_name='stock_set')
    price = CurrencyField()
     
## GAS-Supplier interface
class GASSupplierSolidalPact(models.Model):
    gas = models.ForeignKey(GAS, related_name='pact_set')
    supplier = models.ForeignKey(Supplier, related_name='pact_set')
    
    def setup_accounting(self):
        ## create accounts for logging GAS <-> Supplier transactions
        # GAS-side
        gas_system = self.gas.subject.accounting_system
        gas_system.add_account(parent_path='/expenses/suppliers', name=str(self.supplier.name), kind=types.expense)
        # Supplier-side
        supplier_system = self.supplier.subject.accounting_system
        supplier_system.add_account(parent_path='/incomes/gas', name=str(self.gas.name), kind=types.income)
    
    def save(self, *args, **kwargs):
        # run only at instance creation-time 
        if not self.pk:
            self.setup_accounting() 
        super(GASSupplierSolidalPact, self).save(*args, **kwargs)

## Orders
# GAS -> Supplier   
class GASSupplierStock(models.Model):
    pact = models.ForeignKey(GASSupplierSolidalPact)
    stock = models.ForeignKey(SupplierStock)  
    

class GASSupplierOrder(models.Model):
    pact = models.ForeignKey(GASSupplierSolidalPact, related_name='order_set')
    

class GASSupplierOrderProduct(models.Model):
    order = models.ForeignKey(GASSupplierOrder)
    gas_stock = models.ForeignKey(GASSupplierStock)
    # the price of the Product at the time the GASSupplierOrder was created
    initial_price = CurrencyField()
    # the price of the Product at the time the GASSupplierOrder was sent to the Supplier
    order_price = CurrencyField()
    # the actual price of the Product (as resulting from the invoice)
    delivered_price = CurrencyField(null=True, blank=True)
    # how many items were actually delivered by the Supplier 
    delivered_amount = models.PositiveIntegerField(null=True, blank=True)
    
# GAS member -> GAS
class GASMemberOrder(models.Model):
    purchaser = models.ForeignKey(GASMember)
    ordered_product = models.ForeignKey(GASSupplierOrderProduct)
    # price of the Product at order time
    ordered_price = CurrencyField()
    # how many Product units were ordered by the GAS member
    ordered_amount = models.PositiveIntegerField()
    # how many Product units were withdrawn by the GAS member 
    withdrawn_amount = models.PositiveIntegerField()

#--------------------------- Accounting proxy-classes --------------------------#

class PersonAccountingProxy(AccountingProxy):
    """
    This class is meant to be the place where implementing the accounting API 
    for ``Person``-like economic subjects.
    
    Since it's a subclass of  ``AccountingProxy``, it inherits from its parent 
    all the methods and attributes comprising the *generic* accounting API;
    here, you can add whatever logic is needed to augment that generic API,
    tailoring it to the specific needs of the ``Person``' model.    
    """
    pass

class GasAccountingProxy(AccountingProxy):
    """
    This class is meant to be the place where implementing the accounting API 
    for ``GAS``-like economic subjects.
    
    Since it's a subclass of  ``AccountingProxy``, it inherits from its parent 
    all the methods and attributes comprising the *generic* accounting API;
    here, you can add whatever logic is needed to augment that generic API,
    tailoring it to the specific needs of the ``GAS``' model.    
    """
    pass

class SupplierAccountingProxy(AccountingProxy):
    """
    This class is meant to be the place where implementing the accounting API 
    for ``Supplier``-like economic subjects.
    
    Since it's a subclass of  ``AccountingProxy``, it inherits from its parent 
    all the methods and attributes comprising the *generic* accounting API;
    here, you can add whatever logic is needed to augment that generic API,
    tailoring it to the specific needs of the ``Supplier``' model.    
    """
    pass


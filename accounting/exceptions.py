# Copyright (C) 2011 REES Marche <http://www.reesmarche.org>
#
# This file is part of ``django-simple-accounting``.

# ``django-simple-accounting`` is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# ``django-simple-accounting`` is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with ``django-simple-accounting``. If not, see <http://www.gnu.org/licenses/>.

# definitions of custom exceptions go here

class MalformedAccountTree(Exception):
    """
    Raised if the tree of accounts associated with an accounting system is malformed.
    """
    pass

class SubjectiveAPIError(Exception):
    """
    Raised when a client model can't be declared as *subjective*. 
    """
    pass
        
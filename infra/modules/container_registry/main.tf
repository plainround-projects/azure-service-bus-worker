resource "azurerm_container_registry" "this" {
  #checkov:skip=CKV_AZURE_163:vulnerability scanning needs Microsoft Defender for Containers
  #checkov:skip=CKV_AZURE_164:signed images need the Premium SKU
  #checkov:skip=CKV_AZURE_165:geo-replication needs the Premium SKU
  #checkov:skip=CKV_AZURE_166:image quarantine needs the Premium SKU
  #checkov:skip=CKV_AZURE_167:the untagged-manifest retention policy needs the Premium SKU
  #checkov:skip=CKV_AZURE_233:zone redundancy needs the Premium SKU
  #checkov:skip=CKV_AZURE_237:dedicated data endpoints need the Premium SKU
  #checkov:skip=CKV_AZURE_139:disabling public access needs the Premium SKU and a private endpoint; the pull is authorized by an identity with AcrPull
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = var.sku
  tags                = var.tags

  # No shared admin username and password: images are pulled by an identity holding AcrPull on this registry.
  admin_enabled          = false
  anonymous_pull_enabled = false
}

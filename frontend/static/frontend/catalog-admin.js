/* ═══════════════════════════════════════════════════════════════════════════
   AuraFoods ERP — Storefront Catalog (Products / Categories / Bundles)
   Migrated from the CMS admin dashboard's admin.js (static/js/admin.js).

   Loaded after app.js (see frontend/templates/frontend/app.html), so it
   reuses app.js's already-declared `csrfToken`, `showToast`, `setBtnLoading`,
   `delayedReload` and `apiGet` from the shared top-level script scope instead
   of redefining them. Everything here is scoped to elements carrying
   "data-cat-*" attributes or the "cat-modal-overlay" class, so it never
   touches any of the ERP console's existing forms, tabs or modals — those
   keep using app.js exactly as before. Delete buttons for storefront
   products/categories/bundles use the ERP's own existing
   "data-confirm-post" convention (wired in app.js) rather than anything
   defined here.
   ═══════════════════════════════════════════════════════════════════════════ */

(function () {
  "use strict";

  function byId(id) {
    return document.getElementById(id);
  }

  // ── Modal open/close ────────────────────────────────────────────────────
  function openCatModal(id) {
    const modal = byId(id);
    if (!modal) return;
    modal.classList.add("cat-open");
    document.body.style.overflow = "hidden";
  }

  function closeCatModal(id) {
    const modal = byId(id);
    if (!modal) return;
    modal.classList.remove("cat-open");
    document.body.style.overflow = "";
  }

  function setValue(id, value) {
    const el = byId(id);
    if (el) el.value = value;
  }

  function setChecked(id, value) {
    const el = byId(id);
    if (el) el.checked = !!value;
  }

  // ── Dynamic grammage / variant rows (ported from static/js/admin.js) ────
  let catRowCounter = 0;

  function addGrammageRow(container, weightLabel, price) {
    if (!container) return;
    const row = document.createElement("div");
    row.className = "cat-dyn-row";

    const weightInput = document.createElement("input");
    weightInput.type = "text";
    weightInput.name = "grammage_weight";
    weightInput.placeholder = "e.g. 250g or 1kg";
    weightInput.title = "Weight label, e.g. 250g or 1kg";
    weightInput.style.width = "110px";
    weightInput.value = weightLabel || "";
    row.appendChild(weightInput);

    const priceInput = document.createElement("input");
    priceInput.type = "number";
    priceInput.step = "1";
    priceInput.name = "grammage_price";
    priceInput.placeholder = "Price (Rs.)";
    priceInput.style.width = "96px";
    priceInput.value = price || "";
    row.appendChild(priceInput);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.title = "Remove this grammage option";
    remove.className = "cat-dyn-remove";
    remove.dataset.catAction = "remove-grammage-row";
    row.appendChild(remove);

    container.appendChild(row);
    return row;
  }

  function addVariantRow(container, data) {
    if (!container) return;
    const row = document.createElement("div");
    row.className = "cat-dyn-row";

    // Unique key per row so the server matches each row's checkboxes to the
    // right row without relying on list position.
    const rowKey = "r" + catRowCounter++ + Date.now().toString(36);
    const rowKeyInput = document.createElement("input");
    rowKeyInput.type = "hidden";
    rowKeyInput.name = "variant_row_key";
    rowKeyInput.value = rowKey;
    row.appendChild(rowKeyInput);

    const idInput = document.createElement("input");
    idInput.type = "hidden";
    idInput.name = "variant_ids";
    idInput.value = data ? String(data.id) : "new";
    row.appendChild(idInput);

    const weightInput = document.createElement("input");
    weightInput.type = "text";
    weightInput.name = "variant_weight";
    weightInput.placeholder = "Size e.g. 250g";
    weightInput.style.width = "76px";
    weightInput.value = data ? data.display_weight : "";
    if (data) weightInput.readOnly = true;
    row.appendChild(weightInput);

    function numberInput(name, value, placeholder) {
      const input = document.createElement("input");
      input.type = "number";
      input.step = "1";
      input.name = name;
      input.placeholder = placeholder;
      input.style.width = "64px";
      input.value = value || "";
      return input;
    }
    row.appendChild(numberInput("variant_price", data ? data.price : "", "Price"));
    row.appendChild(numberInput("variant_old_price", data ? data.old_price : "", "Old"));

    function toggleInput(name, checked, label) {
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = name + "__" + rowKey;
      input.value = "1";
      input.checked = !!checked;
      input.title = label;
      row.appendChild(input);
    }
    toggleInput("variant_active", data ? data.active : true, "Active (visible on storefront)");
    toggleInput("variant_sellable", data ? data.sellable : true, "Sellable");

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.title = "Remove this size";
    remove.className = "cat-dyn-remove";
    remove.dataset.catAction = "remove-variant-row";
    row.appendChild(remove);

    container.appendChild(row);
    return row;
  }

  function trackRemovedVariant(id) {
    const tracker = byId("ep_removed_variant_ids");
    if (!tracker) return;
    const values = tracker.value ? tracker.value.split(",") : [];
    if (values.indexOf(String(id)) === -1) values.push(String(id));
    tracker.value = values.join(",");
  }

  // ── Edit Product modal ───────────────────────────────────────────────────
  function editProductModal(id) {
    apiGet("/store/api/product/" + id + "/")
      .then(function (product) {
        const form = byId("editProductForm");
        if (form) form.action = "/admin/product/edit/" + id + "/";
        const grammageOptions = product.grammage_options || {};
        setValue("ep_name", product.name);
        setValue("ep_tagline", product.tagline || "");
        setValue("ep_price", product.price);
        setValue("ep_old_price", product.old_price || 0);
        setValue("ep_weight", product.weight || "200g");
        setValue("ep_category", product.category || product.category_id || "");
        setValue("ep_desc", product.description || "");
        setValue("ep_ing", product.ingredients || "");
        setValue("ep_usage", product.usage || "");
        setChecked("ep_bs", product.best_seller);
        setChecked("ep_na", product.new_arrival);
        setChecked("ep_active", product.active);
        setChecked("ep_featured", product.featured);
        const tracker = byId("ep_removed_variant_ids");
        if (tracker) tracker.value = "";
        const grammageContainer = byId("ep_grammage");
        if (grammageContainer) {
          grammageContainer.replaceChildren();
          Object.keys(grammageOptions).forEach(function (weightLabel) {
            addGrammageRow(grammageContainer, weightLabel, grammageOptions[weightLabel]);
          });
        }
        const variantContainer = byId("ep_variants");
        if (variantContainer) {
          variantContainer.replaceChildren();
          (product.admin_variants || []).forEach(function (variant) {
            addVariantRow(variantContainer, variant);
          });
        }
        openCatModal("editProductModal");
      })
      .catch(function (err) {
        showToast(err.message || "Error loading product", "error");
      });
  }

  function editCatModal(id, name) {
    const form = byId("editCatForm");
    if (form) form.action = "/admin/category/edit/" + id + "/";
    setValue("ec_name", name);
    openCatModal("editCatModal");
  }

  function editBundleModal(id) {
    apiGet("/store/api/bundle/" + id + "/detail/")
      .then(function (bundle) {
        const form = byId("editBundleForm");
        if (form) form.action = "/admin/bundle/edit/" + id + "/";
        setValue("eb_name", bundle.name);
        setValue("eb_items", bundle.items || "");
        setValue("eb_price", bundle.price);
        setValue("eb_old_price", bundle.old_price || 0);
        openCatModal("editBundleModal");
      })
      .catch(function (err) {
        showToast(err.message || "Error loading bundle", "error");
      });
  }

  // ── Manage products in a category / bundle ───────────────────────────────
  function appendManagedProductOption(list, product, checked) {
    const label = document.createElement("label");
    label.className = "cat-checkbox-row";
    if (checked) label.style.background = "rgba(5,150,105,0.06)";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = "product_ids";
    checkbox.value = product.id;
    checkbox.checked = checked;

    const image = document.createElement("img");
    image.src = product.image || "/static/images/hero-spices.jpg";
    image.alt = "";

    const text = document.createElement("span");
    const strong = document.createElement("strong");
    strong.textContent = product.name || "";
    text.appendChild(strong);
    text.appendChild(document.createTextNode(" - Rs." + (product.price || product.display_price || "0.00")));

    const weight = document.createElement("span");
    weight.textContent = product.weight || product.display_weight || "";
    weight.style.marginLeft = "auto";
    weight.style.fontSize = "11px";

    label.appendChild(checkbox);
    label.appendChild(image);
    label.appendChild(text);
    label.appendChild(weight);
    list.appendChild(label);
  }

  function setManagedProductListMessage(list, message) {
    list.replaceChildren();
    const messageBox = document.createElement("div");
    messageBox.textContent = message;
    messageBox.style.textAlign = "center";
    messageBox.style.padding = "1rem";
    messageBox.className = "text-muted";
    list.appendChild(messageBox);
  }

  function manageCatProducts(catId) {
    const list = byId("mcp_product_list");
    const form = byId("manageCatProductsForm");
    if (!list || !form) return;
    form.action = "/admin/category/" + catId + "/manage-products/";
    setManagedProductListMessage(list, "Loading products…");
    openCatModal("manageCatProductsModal");
    apiGet("/store/api/category/" + catId + "/products/")
      .then(function (data) {
        byId("mcp_cat_name").textContent = data.category;
        list.replaceChildren();
        if (!data.all_products.length) {
          setManagedProductListMessage(list, "No products exist. Add products first.");
          return;
        }
        data.all_products.forEach(function (product) {
          appendManagedProductOption(list, product, data.assigned_ids.includes(product.id));
        });
      })
      .catch(function () {
        setManagedProductListMessage(list, "Error loading products.");
      });
  }

  function manageBundleProducts(bundleId) {
    const list = byId("mbp_product_list");
    const form = byId("manageBundleProductsForm");
    if (!list || !form) return;
    form.action = "/admin/bundle/" + bundleId + "/manage-products/";
    setManagedProductListMessage(list, "Loading products…");
    openCatModal("manageBundleProductsModal");
    apiGet("/store/api/bundle/" + bundleId + "/products/")
      .then(function (data) {
        byId("mbp_bundle_name").textContent = data.bundle;
        list.replaceChildren();
        if (!data.all_products.length) {
          setManagedProductListMessage(list, "No products exist.");
          return;
        }
        data.all_products.forEach(function (product) {
          appendManagedProductOption(list, product, data.assigned_ids.includes(product.id));
        });
      })
      .catch(function () {
        setManagedProductListMessage(list, "Error loading products.");
      });
  }

  // ── AJAX submit for all data-cat-ajax forms (add/edit/manage-products) ──
  // These post to the CMS's existing classic (non-JSON) shop endpoints, so we
  // submit as multipart/FormData rather than app.js's JSON apiPost, and stay
  // on the ERP page (reload in place) instead of following the shop view's
  // own redirect.
  function ajaxSubmitClassicForm(form, successMessage, modalIdToClose) {
    const button = form.querySelector("button[type='submit']");
    setBtnLoading(button, true);
    return fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken },
    })
      .then(function (response) {
        if (response.ok) {
          if (modalIdToClose) closeCatModal(modalIdToClose);
          showToast(successMessage, "success");
          delayedReload(1200);
        } else {
          showToast("Error saving — check the required fields.", "error");
          setBtnLoading(button, false);
        }
      })
      .catch(function () {
        showToast("Network error while saving.", "error");
        setBtnLoading(button, false);
      });
  }

  document.addEventListener("submit", function (event) {
    const form = event.target;
    if (!form.matches || !form.matches("[data-cat-ajax]")) return;
    event.preventDefault();
    const modalOverlay = form.closest(".cat-modal-overlay");
    const successMessage = form.dataset.catSuccess || "Saved successfully.";
    ajaxSubmitClassicForm(form, successMessage, modalOverlay ? modalOverlay.id : null);
  });

  // ── Image upload (hidden forms, submitted via AJAX on file selection) ───
  function triggerImageUpload(formId, inputId, action) {
    const form = byId(formId);
    const input = byId(inputId);
    if (!form || !input) return;
    form.action = action;
    input.click();
  }

  ["uploadProductImgInput", "uploadCatImgInput", "uploadBundleImgInput"].forEach(function (inputId) {
    const input = byId(inputId);
    if (!input) return;
    input.addEventListener("change", function () {
      const form = input.form;
      if (!form || !input.files.length) return;
      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken },
      })
        .then(function (response) {
          if (response.ok) {
            showToast("Image updated.", "success");
            delayedReload(900);
          } else {
            showToast("Error uploading image.", "error");
          }
        })
        .catch(function () {
          showToast("Network error while uploading.", "error");
        });
    });
  });

  // ── Delegated click handling ─────────────────────────────────────────────
  document.addEventListener("click", function (event) {
    const closeTrigger = event.target.closest("[data-cat-close-modal]");
    if (closeTrigger) {
      closeCatModal(closeTrigger.dataset.catCloseModal);
      return;
    }

    const editProduct = event.target.closest("[data-cat-edit-product]");
    if (editProduct) {
      editProductModal(editProduct.dataset.catEditProduct);
      return;
    }

    const editCategory = event.target.closest("[data-cat-edit-category]");
    if (editCategory) {
      editCatModal(editCategory.dataset.catEditCategory, editCategory.dataset.name || "");
      return;
    }

    const editBundle = event.target.closest("[data-cat-edit-bundle]");
    if (editBundle) {
      editBundleModal(editBundle.dataset.catEditBundle);
      return;
    }

    const manageCategory = event.target.closest("[data-cat-manage-category-products]");
    if (manageCategory) {
      manageCatProducts(manageCategory.dataset.catManageCategoryProducts);
      return;
    }

    const manageBundle = event.target.closest("[data-cat-manage-bundle-products]");
    if (manageBundle) {
      manageBundleProducts(manageBundle.dataset.catManageBundleProducts);
      return;
    }

    const uploadProduct = event.target.closest("[data-cat-upload-product-image]");
    if (uploadProduct) {
      triggerImageUpload("uploadProductImgForm", "uploadProductImgInput", "/admin/product/image/" + uploadProduct.dataset.catUploadProductImage + "/");
      return;
    }

    const uploadCategory = event.target.closest("[data-cat-upload-category-image]");
    if (uploadCategory) {
      triggerImageUpload("uploadCatImgForm", "uploadCatImgInput", "/admin/category/image/" + uploadCategory.dataset.catUploadCategoryImage + "/");
      return;
    }

    const uploadBundle = event.target.closest("[data-cat-upload-bundle-image]");
    if (uploadBundle) {
      triggerImageUpload("uploadBundleImgForm", "uploadBundleImgInput", "/admin/bundle/image/" + uploadBundle.dataset.catUploadBundleImage + "/");
      return;
    }

    const addVariant = event.target.closest("[data-cat-action='add-variant-row']");
    if (addVariant) {
      addVariantRow(byId("ep_variants"), null);
      return;
    }

    const removeVariant = event.target.closest("[data-cat-action='remove-variant-row']");
    if (removeVariant) {
      const row = removeVariant.closest(".cat-dyn-row");
      if (!row) return;
      const idInput = row.querySelector('input[name="variant_ids"]');
      if (idInput && idInput.value !== "new") trackRemovedVariant(idInput.value);
      row.remove();
      return;
    }

    const addGrammage = event.target.closest("[data-cat-action='add-grammage-row']");
    if (addGrammage) {
      addGrammageRow(byId(addGrammage.dataset.catTarget || "ep_grammage"), "", "");
      return;
    }

    const removeGrammage = event.target.closest("[data-cat-action='remove-grammage-row']");
    if (removeGrammage) {
      const row = removeGrammage.closest(".cat-dyn-row");
      if (row) row.remove();
      return;
    }
  });

  // Close a modal when its backdrop (not its content) is clicked.
  document.querySelectorAll(".cat-modal-overlay").forEach(function (overlay) {
    overlay.addEventListener("click", function (event) {
      if (event.target === overlay) closeCatModal(overlay.id);
    });
  });

  // Escape key closes any open cat-modal.
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    document.querySelectorAll(".cat-modal-overlay.cat-open").forEach(function (overlay) {
      closeCatModal(overlay.id);
    });
  });
})();

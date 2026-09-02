(function () {
    "use strict";

    let variantRowCounter = 0;

    function byId(id) {
        return document.getElementById(id);
    }

    function switchSection(name) {
        document.querySelectorAll(".section").forEach(function (el) {
            el.classList.remove("active");
        });
        document.querySelectorAll(".sidebar-nav a").forEach(function (el) {
            el.classList.remove("active");
        });

        const section = byId("sec-" + name);
        const navLink = document.querySelector('.sidebar-nav a[data-section="' + name + '"]');
        if (!section || !navLink) return;

        section.classList.add("active");
        navLink.classList.add("active");
        window.location.hash = name;
        sessionStorage.setItem("adminSection", name);
    }

    function openModal(id) {
        const modal = byId(id);
        if (!modal) return;
        modal.classList.add("active");
        document.body.style.overflow = "hidden";
    }

    function closeModal(id) {
        const modal = byId(id);
        if (!modal) return;
        modal.classList.remove("active");
        document.body.style.overflow = "";
    }

    function getCsrfToken() {
        const match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function showToast(message) {
        const toast = byId("toast");
        if (!toast) return;
        toast.textContent = message;
        toast.classList.add("show");
        clearTimeout(toast._t);
        toast._t = setTimeout(function () {
            toast.classList.remove("show");
        }, 2500);
    }

    function setValue(id, value) {
        const el = byId(id);
        if (el) el.value = value;
    }

    function setChecked(id, value) {
        const el = byId(id);
        if (el) el.checked = !!value;
    }

    function addGrammageRow(container, weightLabel, price) {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;gap:.35rem;padding:.4rem 0;border-bottom:1px solid rgba(10,10,10,0.05)";

        const weightInput = document.createElement("input");
        weightInput.name = "grammage_weight";
        weightInput.placeholder = "e.g. 250g or 1kg";
        weightInput.title = "Weight label, e.g. 250g or 1kg";
        weightInput.style.cssText = "width:110px;padding:.35rem .4rem;border:1px solid rgba(10,10,10,0.12);border-radius:6px;font-size:.75rem;font-family:inherit";
        weightInput.value = weightLabel || "";
        row.appendChild(weightInput);

        const priceInput = document.createElement("input");
        priceInput.type = "number";
        priceInput.step = "1";
        priceInput.name = "grammage_price";
        priceInput.placeholder = "Price (Rs.)";
        priceInput.style.cssText = "width:96px;padding:.35rem .4rem;border:1px solid rgba(10,10,10,0.12);border-radius:6px;font-size:.75rem;font-family:inherit";
        priceInput.value = price || "";
        row.appendChild(priceInput);

        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "x";
        remove.title = "Remove this grammage option";
        remove.dataset.action = "remove-grammage-row";
        remove.style.cssText = "width:24px;height:24px;flex-shrink:0;border:none;border-radius:4px;background:rgba(10,10,10,0.05);color:var(--muted);cursor:pointer;font-size:.75rem;font-family:inherit;line-height:1";
        row.appendChild(remove);

        container.appendChild(row);
        return row;
    }

    function addVariantRow(container, data) {
        const row = document.createElement("div");
        row.style.cssText = "display:flex;align-items:center;gap:.35rem;padding:.4rem 0;border-bottom:1px solid rgba(10,10,10,0.05)";

        // Unique key for this row so the server can match each row's checkboxes
        // to the right row without relying on list position (which breaks as
        // soon as rows have different checked states).
        const rowKey = "r" + (variantRowCounter++) + Date.now().toString(36);
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
        weightInput.name = "variant_weight";
        weightInput.placeholder = "Size e.g. 250g";
        weightInput.title = "Size, e.g. 200g or 1kg";
        weightInput.style.cssText = "width:76px;padding:.35rem .4rem;border:1px solid rgba(10,10,10,0.12);border-radius:6px;font-size:.75rem;font-family:inherit";
        weightInput.value = data ? data.display_weight : "";
        if (data) weightInput.readOnly = true;
        row.appendChild(weightInput);

        function numberInput(name, value, placeholder) {
            const input = document.createElement("input");
            input.type = "number";
            input.step = "1";
            input.name = name;
            input.placeholder = placeholder;
            input.style.cssText = "width:64px;padding:.35rem .4rem;border:1px solid rgba(10,10,10,0.12);border-radius:6px;font-size:.75rem;font-family:inherit";
            input.value = value || "";
            return input;
        }
        row.appendChild(numberInput("variant_price", data ? data.price : "", "Price"));
        row.appendChild(numberInput("variant_old_price", data ? data.old_price : "", "Old"));

        function toggleInput(name, checked, label) {
            // Each row gets its own uniquely-named field (via rowKey), so the
            // server reads it directly instead of matching a flat list by
            // position. No hidden "0" fallback needed: an absent field is
            // simply treated as unchecked server-side.
            const input = document.createElement("input");
            input.type = "checkbox";
            input.name = name + "__" + rowKey;
            input.value = "1";
            input.checked = !!checked;
            input.style.cssText = "width:16px;height:16px;accent-color:var(--green)";
            input.title = label;
            row.appendChild(input);
        }
        toggleInput("variant_active", data ? data.active : true, "Active (visible on storefront)");
        toggleInput("variant_sellable", data ? data.sellable : true, "Sellable");

        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "x";
        remove.title = "Remove this size";
        remove.dataset.action = "remove-variant-row";
        remove.style.cssText = "width:24px;height:24px;flex-shrink:0;border:none;border-radius:4px;background:rgba(10,10,10,0.05);color:var(--muted);cursor:pointer;font-size:.75rem;font-family:inherit;line-height:1";
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

    function editProductModal(id) {
        fetch("/store/api/product/" + id)
            .then(function (response) {
                return response.json();
            })
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
                const container = byId("ep_variants");
                if (container) {
                    container.replaceChildren();
                    (product.admin_variants || []).forEach(function (variant) {
                        addVariantRow(container, variant);
                    });
                }
                openModal("editProductModal");
            })
            .catch(function () {
                alert("Error loading product");
            });
    }

    function clickUpload(formId, inputId, action) {
        const form = byId(formId);
        const input = byId(inputId);
        if (!form || !input) return;
        form.action = action;
        input.click();
    }

    function editCatModal(id, name) {
        const form = byId("editCatForm");
        if (form) form.action = "/admin/category/edit/" + id + "/";
        setValue("ec_name", name);
        openModal("editCatModal");
    }

    function appendManagedProductOption(list, product, checked) {
        const label = document.createElement("label");
        label.style.cssText = "display:flex;align-items:center;gap:.5rem;padding:.4rem .5rem;background:" + (checked ? "rgba(74,103,65,0.06)" : "#fff") + ";border-radius:4px;font-size:.8125rem;cursor:pointer;border:1px solid " + (checked ? "rgba(74,103,65,0.15)" : "rgba(10,10,10,0.04)");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.name = "product_ids";
        checkbox.value = product.id;
        checkbox.checked = checked;
        checkbox.style.cssText = "width:16px;height:16px;accent-color:var(--green)";
        const image = document.createElement("img");
        image.src = product.image || "/static/images/hero-spices.jpg";
        image.alt = "";
        image.style.cssText = "width:32px;height:32px;border-radius:4px;object-fit:cover";
        const text = document.createElement("span");
        const strong = document.createElement("strong");
        strong.textContent = product.name || "";
        text.appendChild(strong);
        text.appendChild(document.createTextNode(" - Rs." + (product.price || product.display_price || "0.00")));
        const weight = document.createElement("span");
        weight.textContent = product.weight || product.display_weight || "";
        weight.style.cssText = "margin-left:auto;font-size:.6875rem;color:var(--muted)";
        label.appendChild(checkbox);
        label.appendChild(image);
        label.appendChild(text);
        label.appendChild(weight);
        list.appendChild(label);
    }

    function setManagedProductListMessage(list, message, colorName) {
        list.replaceChildren();
        const messageBox = document.createElement("div");
        messageBox.textContent = message;
        messageBox.style.cssText = "text-align:center;padding:1rem;color:var(--" + colorName + ")";
        list.appendChild(messageBox);
    }

    function manageCatProducts(catId) {
        const list = byId("mcp_product_list");
        const form = byId("manageCatProductsForm");
        if (!list || !form) return;
        form.action = "/admin/category/" + catId + "/manage-products/";
        setManagedProductListMessage(list, "Loading products...", "muted");
        openModal("manageCatProductsModal");
        fetch("/store/api/category/" + catId + "/products/")
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                byId("mcp_cat_name").textContent = data.category;
                list.replaceChildren();
                if (data.all_products.length === 0) {
                    setManagedProductListMessage(list, "No products exist. Add products first.", "muted");
                    return;
                }
                data.all_products.forEach(function (product) {
                    appendManagedProductOption(list, product, data.assigned_ids.includes(product.id));
                });
            })
            .catch(function () {
                setManagedProductListMessage(list, "Error loading products.", "red");
            });
    }

    function editBundleModal(id) {
        fetch("/store/api/bundle/" + id + "/detail/")
            .then(function (response) {
                return response.json();
            })
            .then(function (bundle) {
                const form = byId("editBundleForm");
                if (form) form.action = "/admin/bundle/edit/" + id + "/";
                setValue("eb_name", bundle.name);
                setValue("eb_items", bundle.items || "");
                setValue("eb_price", bundle.price);
                setValue("eb_old_price", bundle.old_price || 0);
                openModal("editBundleModal");
            })
            .catch(function () {
                alert("Error loading bundle");
            });
    }

    function manageBundleProducts(bundleId) {
        const list = byId("mbp_product_list");
        const form = byId("manageBundleProductsForm");
        if (!list || !form) return;
        form.action = "/admin/bundle/" + bundleId + "/manage-products/";
        setManagedProductListMessage(list, "Loading products...", "muted");
        openModal("manageBundleProductsModal");
        fetch("/store/api/bundle/" + bundleId + "/products/")
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                byId("mbp_bundle_name").textContent = data.bundle;
                list.replaceChildren();
                if (data.all_products.length === 0) {
                    setManagedProductListMessage(list, "No products exist.", "muted");
                    return;
                }
                data.all_products.forEach(function (product) {
                    appendManagedProductOption(list, product, data.assigned_ids.includes(product.id));
                });
            })
            .catch(function () {
                setManagedProductListMessage(list, "Error loading products.", "red");
            });
    }

    function submitManagedProductsForm(event, modalId, successMessage) {
        event.preventDefault();
        const form = event.target;
        const button = form.querySelector('button[type="submit"]');
        if (button) {
            button.disabled = true;
            button.textContent = "Saving...";
        }
        fetch(form.action, {
            method: "POST",
            body: new FormData(form),
            credentials: "same-origin",
            headers: {"X-CSRFToken": getCsrfToken()},
        })
            .then(function (response) {
                if (response.ok) {
                    closeModal(modalId);
                    showToast(successMessage);
                } else {
                    alert("Error saving");
                }
            })
            .catch(function () {
                alert("Network error");
            })
            .finally(function () {
                if (button) {
                    button.disabled = false;
                    button.textContent = "Save Changes";
                }
            });
    }

    function editWhyModal(id, title, description) {
        const form = byId("editWhyForm");
        if (form) form.action = "/admin/why/edit/" + id + "/";
        setValue("ew_title", title);
        setValue("ew_desc", description);
        openModal("editWhyModal");
    }

    function handleClick(event) {
        const sectionTrigger = event.target.closest("[data-switch-section]");
        if (sectionTrigger) {
            event.preventDefault();
            switchSection(sectionTrigger.dataset.switchSection);
            return;
        }

        const navLink = event.target.closest(".sidebar-nav a[data-section]");
        if (navLink) {
            event.preventDefault();
            switchSection(navLink.dataset.section);
            return;
        }

        const closeTrigger = event.target.closest("[data-close-modal]");
        if (closeTrigger) {
            closeModal(closeTrigger.dataset.closeModal);
            return;
        }

        const fileDrop = event.target.closest("[data-file-drop]");
        if (fileDrop) {
            const input = fileDrop.querySelector('input[type="file"]');
            if (input) input.click();
            return;
        }

        const editProduct = event.target.closest("[data-edit-product]");
        if (editProduct) {
            editProductModal(editProduct.dataset.editProduct);
            return;
        }

        const uploadProduct = event.target.closest("[data-upload-product-image]");
        if (uploadProduct) {
            clickUpload("uploadProductImgForm", "uploadProductImgInput", "/admin/product/image/" + uploadProduct.dataset.uploadProductImage + "/");
            return;
        }

        const uploadBlog = event.target.closest("[data-upload-blog-image]");
        if (uploadBlog) {
            clickUpload("uploadBlogImgForm", "uploadBlogImgInput", "/admin/blog/image/" + uploadBlog.dataset.uploadBlogImage + "/");
            return;
        }

        const uploadCategory = event.target.closest("[data-upload-category-image]");
        if (uploadCategory) {
            clickUpload("uploadCatImgForm", "uploadCatImgInput", "/admin/category/image/" + uploadCategory.dataset.uploadCategoryImage + "/");
            return;
        }

        const uploadBundle = event.target.closest("[data-upload-bundle-image]");
        if (uploadBundle) {
            clickUpload("uploadBundleImgForm", "uploadBundleImgInput", "/admin/bundle/image/" + uploadBundle.dataset.uploadBundleImage + "/");
            return;
        }

        const editCategory = event.target.closest("[data-edit-category]");
        if (editCategory) {
            editCatModal(editCategory.dataset.editCategory, editCategory.dataset.name || "");
            return;
        }

        const manageCategory = event.target.closest("[data-manage-category-products]");
        if (manageCategory) {
            manageCatProducts(manageCategory.dataset.manageCategoryProducts);
            return;
        }

        const editBundle = event.target.closest("[data-edit-bundle]");
        if (editBundle) {
            editBundleModal(editBundle.dataset.editBundle);
            return;
        }

        const manageBundle = event.target.closest("[data-manage-bundle-products]");
        if (manageBundle) {
            manageBundleProducts(manageBundle.dataset.manageBundleProducts);
            return;
        }

        const editWhy = event.target.closest("[data-edit-why]");
        if (editWhy) {
            editWhyModal(editWhy.dataset.editWhy, editWhy.dataset.title || "", editWhy.dataset.description || "");
            return;
        }

        const addVariant = event.target.closest("[data-action='add-variant-row']");
        if (addVariant) {
            const container = byId("ep_variants");
            if (container) addVariantRow(container, null);
            return;
        }

        const removeVariant = event.target.closest("[data-action='remove-variant-row']");
        if (removeVariant) {
            const row = removeVariant.closest("div");
            if (!row) return;
            const idInput = row.querySelector('input[name="variant_ids"]');
            if (idInput && idInput.value !== "new") {
                trackRemovedVariant(idInput.value);
            }
            row.remove();
            return;
        }

        const addGrammage = event.target.closest("[data-action='add-grammage-row']");
        if (addGrammage) {
            const container = byId(addGrammage.dataset.target || "ep_grammage");
            if (container) addGrammageRow(container, "", "");
            return;
        }

        const removeGrammage = event.target.closest("[data-action='remove-grammage-row']");
        if (removeGrammage) {
            const row = removeGrammage.closest("div");
            if (row) row.remove();
        }
    }

    function handleSubmit(event) {
        const active = document.querySelector(".section.active");
        if (active) {
            sessionStorage.setItem("adminSection", active.id.replace("sec-", ""));
        }

        const confirmForm = event.target.closest("form.js-confirm");
        if (confirmForm && !window.confirm(confirmForm.dataset.confirm || "Are you sure?")) {
            event.preventDefault();
            return;
        }

        const asyncType = event.target.dataset.asyncSubmit;
        if (asyncType === "bundle-products") {
            submitManagedProductsForm(event, "manageBundleProductsModal", "Bundle products updated!");
        } else if (asyncType === "category-products") {
            submitManagedProductsForm(event, "manageCatProductsModal", "Category products updated!");
        }
    }

    function restoreSection() {
        const savedSection = sessionStorage.getItem("adminSection");
        if (savedSection && byId("sec-" + savedSection)) {
            switchSection(savedSection);
            sessionStorage.removeItem("adminSection");
            return;
        }
        if (window.location.hash) {
            const name = window.location.hash.replace("#", "");
            if (byId("sec-" + name)) switchSection(name);
        }
    }

    document.addEventListener("click", handleClick);
    document.addEventListener("submit", handleSubmit);
    document.querySelectorAll(".modal-overlay").forEach(function (overlay) {
        overlay.addEventListener("click", function (event) {
            if (event.target === overlay) {
                overlay.classList.remove("active");
                document.body.style.overflow = "";
            }
        });
    });
    document.querySelectorAll(".js-auto-submit").forEach(function (input) {
        input.addEventListener("change", function () {
            if (input.form) input.form.submit();
        });
    });

    restoreSection();
    if (new URLSearchParams(window.location.search).get("saved")) {
        showToast("Changes saved successfully!");
    }
})();
